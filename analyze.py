import json
import glob
import os
import re
import time
import sys
from collections import defaultdict
from janome.tokenizer import Tokenizer

# Define paths
transcript_pattern = "transcripts/*.txt.md"
keywords_file = "keywords.json"
output_dir = "public"
cache_file = "janome_cache.json"

# --- Caching Setup ---
try:
    with open(cache_file, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cache_data = {}

# Ensure output directory exists
os.makedirs(output_dir, exist_ok=True)

print("Loading transcripts...")
# Load transcripts, extract titles, and clean content
transcript_files = glob.glob(transcript_pattern)
transcripts_data = {}
for filepath in transcript_files:
    filename = os.path.basename(filepath)
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        if not lines:
            continue

        raw_title = lines[0].strip()
        cleaned_title = raw_title.split(' - ')[0]
        content = "".join(lines[1:]).strip()

        transcripts_data[filename] = {
            "title": cleaned_title,
            "content": content,
            "filepath": filepath
        }
print(f"Loaded {len(transcripts_data)} transcripts.")

# --- Tokenization with Caching ---
t = Tokenizer()
all_tokens = {}
needs_cache_update = False

print("Tokenizing transcripts (using cache where possible)...")
for filename, data in transcripts_data.items():
    filepath = data['filepath']
    mtime = os.path.getmtime(filepath)
    
    if filename in cache_data and cache_data[filename].get('mtime') == mtime:
        all_tokens[filename] = cache_data[filename]['tokens']
    else:
        print(f"  - Analyzing: {filename}")
        needs_cache_update = True
        tokens = list(t.tokenize(data['content']))
        
        serializable_tokens = [
            {'surface': token.surface, 'part_of_speech': token.part_of_speech, 'infl_form': token.infl_form}
            for token in tokens
        ]
        
        all_tokens[filename] = serializable_tokens
        cache_data[filename] = {
            'mtime': mtime,
            'tokens': serializable_tokens
        }

if needs_cache_update:
    print(f"Saving token cache to {cache_file}...")
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False)

# --- Keyword Gathering (now uses `all_tokens`) ---
print("Gathering keyword candidates...")

# Helper function to check if a string is purely Katakana
def is_purely_katakana(text):
    return re.fullmatch(r'[\u30A0-\u30FF\u30FC]+', text)

# Helper function to check if a string is purely English (letters, numbers, spaces)
def is_purely_english(text):
    return re.fullmatch(r'[a-zA-Z0-9\s]+', text)

# 1. Load keywords from JSON file
json_keywords = set()
try:
    with open(keywords_file, 'r', encoding='utf-8') as f:
        keywords_data = json.load(f)
        for item in keywords_data.get('keywords', []):
            json_keywords.add(item.get('keyword', ''))
    print(f"Loaded {len(json_keywords)} keywords from '{keywords_file}'.")
except (FileNotFoundError, json.JSONDecodeError):
    print(f"Warning: Could not load or parse '{keywords_file}'. Continuing without it.")

# 2. Extract Katakana keywords
katakana_keywords = set()
katakana_pattern = re.compile(r'[\u30A0-\u30FF\u30FC]{3,}')
for data in transcripts_data.values():
    found_katakana = katakana_pattern.findall(data['content'])
    katakana_keywords.update(found_katakana)
print(f"Extracted {len(katakana_keywords)} unique Katakana keywords.")

# 2.5. Extract English keywords
english_keywords = set()
english_pattern = re.compile(r'[a-zA-Z0-9]{3,}(?: [a-zA-Z0-9]+)*')
for data in transcripts_data.values():
    found_english = english_pattern.findall(data['content'])
    english_keywords.update(found_english)
print(f"Extracted {len(english_keywords)} unique English keywords.")

# 3. Extract Nouns and Noun Phrases from tokens
proper_noun_keywords = set()
extracted_noun_phrases = set()
modifier_noun_phrases = set()
verb_nominalization_phrases = set()
prefix_noun_phrases = set()

# Counters for verb-related patterns
pattern_e_count = 0
pattern_f_count = 0
pattern_g_count = 0

for filename, tokens in all_tokens.items():
    # Comprehensive Noun Phrase Extraction (replaces Pattern A and B logic)
    current_phrase_tokens = []
    for token in tokens:
        pos_main = token['part_of_speech'].split(',')[0]
        pos_sub = token['part_of_speech'].split(',')[1] if len(token['part_of_speech'].split(',')) > 1 else ''
        pos_full = token['part_of_speech']

        # --- Conditions to continue the phrase ---
        is_noun = (pos_main == '名詞')
        is_particle_no = (token['surface'] == 'の' and pos_full.startswith('助詞,連体化') and len(current_phrase_tokens) > 0)
        is_particle_toiu = (token['surface'] == 'という' and pos_main == '助詞' and len(current_phrase_tokens) > 0)
        is_prefix = (pos_main == '接頭詞')

        is_aux_na_connective = False
        if len(current_phrase_tokens) > 0 and token['surface'] == 'な' and pos_full.startswith('助動詞'):
            pos_list = pos_full.split(',')
            if len(pos_list) > 5:
                if pos_list[5] == '体言接続':
                    is_aux_na_connective = True
            else:
                is_aux_na_connective = True

        if is_noun or is_particle_no or is_aux_na_connective or is_particle_toiu or is_prefix:
            if len(current_phrase_tokens) == 0 and is_noun and (pos_sub == '非自立' or token['surface'] == '名'):
                pass
            else:
                current_phrase_tokens.append(token['surface'])
                if is_noun and pos_sub == '固有名詞':
                    surface = token['surface'].strip()
                    if len(surface) >= 2 and not surface.isnumeric():
                        proper_noun_keywords.add(surface)
        else:
            if len(current_phrase_tokens) >= 2:
                if current_phrase_tokens[-1] not in ['の', 'な', 'という']:
                    extracted_noun_phrases.add("".join(current_phrase_tokens))
            current_phrase_tokens = []

    if len(current_phrase_tokens) >= 2:
        if current_phrase_tokens[-1] not in ['の', 'な', 'という']:
            extracted_noun_phrases.add("".join(current_phrase_tokens))

    # Patterns C, D, E, F, G, H
    for i in range(len(tokens) - 2):
        t1, t2, t3 = tokens[i], tokens[i+1], tokens[i+2]
        pos1 = t1['part_of_speech'].split(',')[0]
        pos3 = t3['part_of_speech'].split(',')[0]
        if pos1 == '形容動詞' and t2['surface'] == 'な' and t2['part_of_speech'].startswith('助詞,連体化') and pos3 == '名詞':
            modifier_noun_phrases.add(t1['surface'] + t2['surface'] + t3['surface'])

    for i in range(len(tokens) - 1):
        t1, t2 = tokens[i], tokens[i+1]
        pos1 = t1['part_of_speech'].split(',')[0]
        pos2 = t2['part_of_speech'].split(',')[0]
        pos1_conj_form = t1['infl_form']

        if pos1 == '形容詞' and pos2 == '名詞':
            modifier_noun_phrases.add(t1['surface'] + t2['surface'])
        if pos1 == '連体詞' and pos2 == '名詞':
            if t1['surface'] not in ['この', 'その', 'あの', 'どの', 'こんな', 'そんな', 'あんな', 'どんな', 'こういう', 'そういう', 'ああいう', 'どういう']:
                modifier_noun_phrases.add(t1['surface'] + t2['surface'])
        if (pos1 == '動詞' and pos1_conj_form == '基本形' and pos2 == '名詞'):
            # ただし、終止形 + 「こと」「もの」の組み合わせは verb_nominalization_phrases で処理するので除外
            if not (pos1_conj_form == '終止形' and (t2['surface'] == 'こと' or t2['surface'] == 'もの')):
                pattern_e_count += 1
                modifier_noun_phrases.add(t1['surface'] + t2['surface'])
        if (pos1 == '動詞' and pos1_conj_form == '基本形' and pos2 == '名詞' and (t2['surface'] == 'こと' or t2['surface'] == 'もの')):
            pattern_f_count += 1
            verb_nominalization_phrases.add(t1['surface'] + t2['surface'])
        if (pos1 == '動詞' and pos1_conj_form == '連用形' and pos2 == '名詞' and t2['surface'] == '方'):
            pattern_g_count += 1
            verb_nominalization_phrases.add(t1['surface'] + t2['surface'])
        if pos1 == '接頭詞' and pos2 == '名詞':
            prefix_noun_phrases.add(t1['surface'] + t2['surface'])

print(f"Extracted {len(proper_noun_keywords)} unique proper nouns.")
print(f"Extracted {len(extracted_noun_phrases)} unique noun phrases (Patterns A, B combined).")
print(f"Extracted {len(modifier_noun_phrases)} modifier-noun phrases (Patterns C,D,E).")
print(f"Extracted {len(verb_nominalization_phrases)} verb nominalization phrases (Patterns F,G).")
print(f"Extracted {len(prefix_noun_phrases)} prefix-noun phrases (Pattern H).")
print(f"  - 動詞+名詞 (E): {pattern_e_count} keywords")
print(f"  - 動詞+こと/もの (F): {pattern_f_count} keywords")
print(f"  - 動詞+方 (G): {pattern_g_count} keywords")

# --- New: Long Phrase Extraction ---
print("Extracting long phrases based on modifier + verb patterns...")
long_phrases = set()
for filename, tokens in all_tokens.items():
    i = 0
    while i < len(tokens):
        # --- Step 1: Find Modifier Phrase ---
        modifier_tokens = []
        j = i
        while j < len(tokens):
            pos_main = tokens[j]['part_of_speech'].split(',')[0]
            
            is_adverb = (pos_main == '副詞')
            
            is_adjectival_verb = False
            if pos_main == '形容動詞' and j + 1 < len(tokens) and tokens[j+1]['surface'] == 'に':
                is_adjectival_verb = True

            if is_adverb:
                modifier_tokens.append(tokens[j])
                j += 1
            elif is_adjectival_verb:
                modifier_tokens.append(tokens[j])
                modifier_tokens.append(tokens[j+1])
                j += 2
            else:
                break
        
        modifier_phrase = "".join([t['surface'] for t in modifier_tokens])
        
        # --- Step 2: Find Body Phrase ---
        body_tokens = []
        k = j
        # Starts with a verb in its base form
        if k < len(tokens):
            pos_main_k = tokens[k]['part_of_speech'].split(',')[0]
            infl_form_k = tokens[k]['infl_form']
            
            if pos_main_k == '動詞' and infl_form_k == '基本形':
                body_tokens.append(tokens[k])
                k += 1
                
                # Continue with nouns, adjectives, or 'の' particles
                while k < len(tokens):
                    pos_main_k_cont = tokens[k]['part_of_speech'].split(',')[0]
                    surface_k_cont = tokens[k]['surface']
                    
                    is_noun = (pos_main_k_cont == '名詞')
                    is_adjective = (pos_main_k_cont == '形容詞')
                    is_particle_no = (surface_k_cont == 'の' and pos_main_k_cont == '助詞')

                    if is_noun or is_adjective or is_particle_no:
                        body_tokens.append(tokens[k])
                        k += 1
                    else:
                        break
        
        body_phrase = "".join([t['surface'] for t in body_tokens])

        # --- Step 3: Combine and Add to Set ---
        if body_phrase:
            # Add the body phrase itself (e.g., "話すこと")
            if len(body_tokens) >= 2:
                long_phrases.add(body_phrase)

            # Add the combined phrase if a modifier exists (e.g., "ゆっくり話すこと")
            if modifier_phrase and len(modifier_tokens) + len(body_tokens) >= 3:
                 long_phrases.add(modifier_phrase + body_phrase)
        
        # Move the main index 'i' forward
        if k > i:
            i = k
        else:
            i += 1

print(f"Extracted {len(long_phrases)} new long phrases.")

# --- New: Parallel Structure Extraction ---
print("Extracting parallel phrases...")
parallel_phrases = set()
for filename, tokens in all_tokens.items():
    parallel_particles = {'と', 'や', 'か'}
    max_window_size = 3  # 最大で前後3トークンまで比較

    for i in range(1, len(tokens) - 1):
        token = tokens[i]
        
        if token['surface'] in parallel_particles:
            for window_size in range(1, max_window_size + 1):
                if i - window_size < 0 or i + window_size >= len(tokens):
                    continue

                phrase_a_tokens = tokens[i-window_size : i]
                phrase_b_tokens = tokens[i+1 : i+1+window_size]

                if not phrase_a_tokens or not phrase_b_tokens:
                    continue

                pos_pattern_a = [t['part_of_speech'].split(',')[0] for t in phrase_a_tokens]
                pos_pattern_b = [t['part_of_speech'].split(',')[0] for t in phrase_b_tokens]

                if pos_pattern_a == pos_pattern_b:
                    if phrase_a_tokens[0]['part_of_speech'].split(',')[0] in ['助詞', '助動詞', '記号'] or \
                       phrase_b_tokens[0]['part_of_speech'].split(',')[0] in ['助詞', '助動詞', '記号']:
                        continue

                    surface_a = "".join([t['surface'] for t in phrase_a_tokens])
                    surface_b = "".join([t['surface'] for t in phrase_b_tokens])
                    
                    combined_phrase = surface_a + token['surface'] + surface_b
                    
                    if len(combined_phrase) > 3:
                        parallel_phrases.add(combined_phrase)

print(f"Extracted {len(parallel_phrases)} new parallel phrases.")


# 4. Combine all keyword sources
all_keywords = json_keywords.union(katakana_keywords).union(english_keywords).union(proper_noun_keywords).union(extracted_noun_phrases).union(modifier_noun_phrases).union(verb_nominalization_phrases).union(prefix_noun_phrases).union(long_phrases).union(parallel_phrases)
print(f"Total unique keyword candidates: {len(all_keywords)}")

# --- Filtering and Mapping ---
print("Filtering and mapping keywords...")
start_time = time.time()

keyword_to_episodes = defaultdict(list)
escaped_keywords = [re.escape(kw) for kw in all_keywords if kw]

# --- Regex Chunking ---
chunk_size = 500  # Process 500 keywords at a time
keyword_chunks = [escaped_keywords[i:i + chunk_size] for i in range(0, len(escaped_keywords), chunk_size)]
regex_chunks = [re.compile('|'.join(chunk)) for chunk in keyword_chunks if chunk]
# --------------------

if regex_chunks:
    for filename, data in transcripts_data.items():
        content = data['content']
        found_keywords_in_file = set()
        for regex in regex_chunks:
            found_keywords_in_file.update(regex.findall(content))
        for keyword in found_keywords_in_file:
            keyword_to_episodes[keyword].append(filename)
else:
    print("No keywords to map.")

end_time = time.time()
print(f"Finished mapping. Duration: {end_time - start_time:.2f} seconds")

# --- New Filter Order ---

# 1. --- Final Filtering by Episode Count (run first) ---
total_episode_count = len(transcripts_data)
print("Applying frequency filter...")
frequent_keywords_map = {
    keyword: episodes
    for keyword, episodes in keyword_to_episodes.items()
    if 2 < len(episodes) and (len(episodes) / total_episode_count) < 0.8
}
print(f"Keywords after frequency filter: {len(frequent_keywords_map)}")

# 2. --- Post-processing: Remove substring keywords (run second on smaller set) ---
print("Applying substring filter...")
start_time_ss = time.time()

keyword_set = set(frequent_keywords_map.keys())
keywords_to_remove = set()
similarity_threshold_episodes = total_episode_count * 0.05 

sorted_keywords = sorted(list(keyword_set), key=len, reverse=True)

for longer_keyword in sorted_keywords:
    if longer_keyword in keywords_to_remove:
        continue

    substrings = {
        longer_keyword[i:j] 
        for i in range(len(longer_keyword)) 
        for j in range(i, len(longer_keyword) + 1)
    }
    substrings.discard(longer_keyword)
    substrings.discard("")

    for shorter_keyword in substrings:
        if shorter_keyword in keywords_to_remove:
            continue

        if shorter_keyword in keyword_set:
            longer_episodes = frequent_keywords_map.get(longer_keyword, [])
            shorter_episodes = frequent_keywords_map.get(shorter_keyword, [])
            
            if not shorter_episodes:
                continue

            if abs(len(longer_episodes) - len(shorter_episodes)) <= similarity_threshold_episodes:
                keywords_to_remove.add(shorter_keyword)

final_keywords = keyword_set - keywords_to_remove

end_time_ss = time.time()
print(f"Finished substring filter. Duration: {end_time_ss - start_time_ss:.2f} seconds")
print(f"Total keywords after all filters: {len(final_keywords)}")

# --- Finalizing JSONs ---
filtered_keyword_to_episodes = {
    keyword: episodes
    for keyword, episodes in frequent_keywords_map.items()
    if keyword in final_keywords
}

valid_keywords = set(filtered_keyword_to_episodes.keys())
episode_to_keywords = defaultdict(list)
for filename, data in transcripts_data.items():
    found_keywords = sorted([kw for kw in valid_keywords if kw in data['content']])
    if found_keywords:
        episode_to_keywords[filename] = found_keywords

output_paths = {
    'keyword_to_episodes.json': filtered_keyword_to_episodes,
    'episode_to_keywords.json': episode_to_keywords,
    'transcripts.json': {fn: {'title': d['title'], 'content': d['content']} for fn, d in transcripts_data.items()}
}

# --- Task 2: Save filtered json_keywords to a separate file ---
filtered_json_keywords = {kw for kw in json_keywords if kw in filtered_keyword_to_episodes}
output_paths['json_source_keywords.json'] = list(filtered_json_keywords)

print(f"Writing {len(output_paths)} JSON files to '{output_dir}' directory...")
for filename, data in output_paths.items():
    with open(os.path.join(output_dir, filename), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

print("Analysis complete. JSON files have been regenerated.")
