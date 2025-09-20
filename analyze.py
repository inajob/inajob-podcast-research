
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

# --- Keyword Gathering (Refactored) ---
print("Gathering keyword candidates using chunking method...")

def create_base_chunks(tokens):
    chunks = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        pos = token['part_of_speech'].split(',')[0]

        # Rule 1: Noun Phrases (including prefixes)
        if pos == '接頭詞' or pos == '名詞':
            j = i
            chunk_tokens = []
            while j < len(tokens):
                current_pos = tokens[j]['part_of_speech'].split(',')[0]
                if current_pos == '名詞' or current_pos == '接頭詞':
                    chunk_tokens.append(tokens[j])
                    j += 1
                else:
                    break
            if chunk_tokens:
                chunks.append({
                    'surface': "".join([t['surface'] for t in chunk_tokens]),
                    'tokens': chunk_tokens,
                    'pos': '名詞句' if len(chunk_tokens) > 1 or chunk_tokens[0]['part_of_speech'].split(',')[0] == '接頭詞' else '名詞'
                })
                i = j
                continue

        # Rule 2: Adjective/Adverbial Phrases
        if pos in ['形容詞', '連体詞', '副詞', '形容動詞']:
            chunks.append({
                'surface': token['surface'],
                'tokens': [token],
                'pos': pos
            })
            i += 1
            continue

        # Rule 3: Verb Phrases (verb + auxiliary verbs)
        if pos == '動詞':
            j = i
            chunk_tokens = [tokens[j]]
            j += 1
            while j < len(tokens):
                current_pos = tokens[j]['part_of_speech'].split(',')[0]
                if current_pos == '助動詞':
                    chunk_tokens.append(tokens[j])
                    j += 1
                else:
                    break
            chunks.append({
                'surface': "".join([t['surface'] for t in chunk_tokens]),
                'tokens': chunk_tokens,
                'pos': '動詞句'
            })
            i = j
            continue

        # If no rule matches, add token as a miscellaneous chunk
        chunks.append({
            'surface': token['surface'],
            'tokens': [token],
            'pos': pos
        })
        i += 1
    return chunks

def combine_chunks(chunks):
    while True:
        did_combine = False
        new_chunks = []
        i = 0
        while i < len(chunks):
            # Rule A: Noun Phrase + Attributive Particle ('の') + Noun Phrase
            if i + 2 < len(chunks) and \
               chunks[i]['pos'] in ['名詞句', '名詞'] and \
               chunks[i+1]['pos'] == '助詞' and len(chunks[i+1]['tokens']) == 1 and chunks[i+1]['tokens'][0]['part_of_speech'].split(',')[1] == '連体化' and \
               chunks[i+2]['pos'] in ['名詞句', '名詞']:
                
                combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens'] + chunks[i+2]['tokens']
                new_chunk = {
                    'surface': "".join([t['surface'] for t in combined_tokens]),
                    'tokens': combined_tokens,
                    'pos': '名詞句'  # Result is a noun phrase
                }
                new_chunks.append(new_chunk)
                i += 3
                did_combine = True
                continue

            # Rule B: Modifier + Modified
            if i + 1 < len(chunks) and \
               chunks[i]['pos'] in ['形容詞', '連体詞', '副詞', '形容動詞'] and \
               chunks[i+1]['pos'] in ['名詞句', '動詞句', '形容詞', '名詞']:
                
                combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens']
                new_chunk = {
                    'surface': "".join([t['surface'] for t in combined_tokens]),
                    'tokens': combined_tokens,
                    'pos': chunks[i+1]['pos']  # Inherit POS from the modified chunk
                }
                new_chunks.append(new_chunk)
                i += 2
                did_combine = True
                continue

                i += 3
                did_combine = True
                continue

            # Rule I: Verb Phrase + Connective Particle + Verb Phrase (Moved Up)
            if i + 2 < len(chunks) and \
               chunks[i]['pos'] == '動詞句' and \
               chunks[i+1]['pos'] == '助詞' and len(chunks[i+1]['tokens']) == 1 and chunks[i+1]['tokens'][0]['part_of_speech'].split(',')[1] == '接続助詞' and \
               chunks[i+2]['pos'] == '動詞句':
                
                combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens'] + chunks[i+2]['tokens']
                new_chunk = {
                    'surface': "".join([t['surface'] for t in combined_tokens]),
                    'tokens': combined_tokens,
                    'pos': '動詞句'  # Result is a longer verb phrase
                }
                new_chunks.append(new_chunk)
                i += 3
                did_combine = True
                continue

            # Rule C: Noun Phrase + を + Verb Phrase
            if i + 2 < len(chunks) and \
               chunks[i]['pos'] in ['名詞句', '名詞'] and \
               chunks[i+1]['surface'] == 'を' and chunks[i+1]['pos'] == '助詞' and \
               chunks[i+2]['pos'] == '動詞句':
                
                combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens'] + chunks[i+2]['tokens']

            # Rule D: Noun Phrase + が/は + Adjective/Adjectival Verb
            if i + 2 < len(chunks) and \
               chunks[i]['pos'] in ['名詞句', '名詞'] and \
               chunks[i+1]['pos'] == '助詞' and chunks[i+1]['surface'] in ['が', 'は'] and \
               chunks[i+2]['pos'] in ['形容詞', '形容動詞']:
                
                combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens'] + chunks[i+2]['tokens']
                new_chunk = {
                    'surface': "".join([t['surface'] for t in combined_tokens]),
                    'tokens': combined_tokens,
                    'pos': chunks[i+2]['pos'] + '句' # Result is an adjectival phrase
                }
                new_chunks.append(new_chunk)
                i += 3
                did_combine = True
                continue

            # Rule E: Parallel Structures (A and B, A or B)
            if i + 2 < len(chunks) and \
               chunks[i+1]['pos'] == '助詞' and len(chunks[i+1]['tokens']) == 1 and chunks[i+1]['tokens'][0]['part_of_speech'].split(',')[1] == '並立助詞':
                
                pos_a = chunks[i]['pos']
                pos_b = chunks[i+2]['pos']
                
                is_noun_pair = (pos_a in ['名詞', '名詞句'] and pos_b in ['名詞', '名詞句'])
                
                if is_noun_pair or (pos_a == pos_b):
                    combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens'] + chunks[i+2]['tokens']
                    new_chunk = {
                        'surface': "".join([t['surface'] for t in combined_tokens]),
                        'tokens': combined_tokens,
                        'pos': pos_a # Inherit POS from the first chunk
                    }
                    new_chunks.append(new_chunk)
                    i += 3
                    did_combine = True
                    continue

            # Rule F: Cause/Reason (A kara/node B)
            if i + 2 < len(chunks) and \
               chunks[i+1]['pos'] == '助詞' and chunks[i+1]['surface'] in ['ので', 'から']:
                
                pos_a = chunks[i]['pos']
                pos_b = chunks[i+2]['pos']

                if pos_a not in ['助詞', '記号'] and pos_b not in ['助詞', '記号']:
                    combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens'] + chunks[i+2]['tokens']
                    new_chunk = {
                        'surface': "".join([t['surface'] for t in combined_tokens]),
                        'tokens': combined_tokens,
                        'pos': pos_b # Inherit POS from the second chunk (the result)
                    }
                    new_chunks.append(new_chunk)
                    i += 3
                    did_combine = True
                    continue

            # Rule G: Verb Phrase modifying a Noun Phrase
            if i + 1 < len(chunks) and \
               chunks[i]['pos'] == '動詞句' and \
               chunks[i+1]['pos'] in ['名詞句', '名詞']:
                
                last_token_in_verb_phrase = chunks[i]['tokens'][-1]
                # The actual verb is the last token before any auxiliary verbs
                verb_token = None
                for t in reversed(chunks[i]['tokens']):
                    if t['part_of_speech'].split(',')[0] == '動詞':
                        verb_token = t
                        break
                
                if verb_token and verb_token['infl_form'] in ['基本形', '連体形']:
                    combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens']
                    new_chunk = {
                        'surface': "".join([t['surface'] for t in combined_tokens]),
                        'tokens': combined_tokens,
                        'pos': '名詞句' # The result is a qualified noun phrase
                    }
                    new_chunks.append(new_chunk)
                    i += 2
                    did_combine = True
                    continue

            # Rule H: Verb Phrase ending with Auxiliary Verb modifying a Noun Phrase
            if i + 1 < len(chunks) and \
               chunks[i]['pos'] == '動詞句' and \
               chunks[i+1]['pos'] in ['名詞句', '名詞']:
                
                last_token_in_verb_phrase = chunks[i]['tokens'][-1]
                
                # Check if the last token of the verb phrase is an auxiliary verb
                if last_token_in_verb_phrase['part_of_speech'].split(',')[0] == '助動詞':
                    combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens']
                    new_chunk = {
                        'surface': "".join([t['surface'] for t in combined_tokens]),
                        'tokens': combined_tokens,
                        'pos': '名詞句' # The result is a qualified noun phrase
                    }
                    new_chunks.append(new_chunk)
                    i += 2
                    did_combine = True
                    continue

            # Rule I: Verb Phrase + Connective Particle + Verb Phrase
            if i + 2 < len(chunks) and \
               chunks[i]['pos'] == '動詞句' and \
               chunks[i+1]['pos'] == '助詞' and len(chunks[i+1]['tokens']) == 1 and chunks[i+1]['tokens'][0]['part_of_speech'].split(',')[1] == '接続助詞' and \
               chunks[i+2]['pos'] == '動詞句':
                
                combined_tokens = chunks[i]['tokens'] + chunks[i+1]['tokens'] + chunks[i+2]['tokens']
                new_chunk = {
                    'surface': "".join([t['surface'] for t in combined_tokens]),
                    'tokens': combined_tokens,
                    'pos': '動詞句'  # Result is a longer verb phrase
                }
                new_chunks.append(new_chunk)
                i += 3
                did_combine = True
                continue

            # No combination, add the current chunk and move on
            new_chunks.append(chunks[i])
            i += 1
        
        chunks = new_chunks
        if not did_combine:
            break
            
    return chunks

def cleanup_keywords(keywords_to_clean, chunk_info_dict):
    print("Cleaning up short keywords...")
    cleaned_keywords = set()
    removed_count = 0
    for kw in keywords_to_clean:
        is_short_single_noun = False
        if len(kw) <= 2 and kw in chunk_info_dict:
            is_single_noun_only = True
            for chunk_pos in chunk_info_dict[kw]:
                if chunk_pos != '名詞':
                    is_single_noun_only = False
                    break
            if is_single_noun_only:
                is_short_single_noun = True
        
        if not is_short_single_noun:
            cleaned_keywords.add(kw)
        else:
            removed_count += 1
            
    print(f"Removed {removed_count} short single-noun keywords.")
    return cleaned_keywords

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

# 2. Extract Katakana & English keywords
katakana_keywords = set()
english_keywords = set()
katakana_pattern = re.compile(r'[\u30A0-\u30FF\u30FC]{3,}')
english_pattern = re.compile(r'[a-zA-Z0-9]{3,}(?: [a-zA-Z0-9]+)*')
for data in transcripts_data.values():
    katakana_keywords.update(katakana_pattern.findall(data['content']))
    english_keywords.update(english_pattern.findall(data['content']))
print(f"Extracted {len(katakana_keywords)} unique Katakana keywords.")
print(f"Extracted {len(english_keywords)} unique English keywords.")

# 3. Generate keywords from tokens using chunking method
all_generated_chunks = defaultdict(set)
for filename, tokens in all_tokens.items():
    base_chunks = create_base_chunks(tokens)
    # Add base chunks
    for chunk in base_chunks:
        if len(chunk['surface']) > 1:
             all_generated_chunks[chunk['surface']].add(chunk['pos'])

    combined_chunks = combine_chunks(base_chunks)
    # Add combined chunks
    for chunk in combined_chunks:
        if len(chunk['surface']) > 1:
             all_generated_chunks[chunk['surface']].add(chunk['pos'])

print(f"Generated {len(all_generated_chunks)} unique keyword surfaces from tokens.")

# 4. Combine all keyword sources
all_keywords = json_keywords.union(katakana_keywords).union(english_keywords).union(all_generated_chunks.keys())
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

final_keywords_after_substring = keyword_set - keywords_to_remove
end_time_ss = time.time()
print(f"Finished substring filter. Duration: {end_time_ss - start_time_ss:.2f} seconds")

# 3. --- Final Cleanup: Remove short, non-compound nouns ---
final_keywords = cleanup_keywords(final_keywords_after_substring, all_generated_chunks)

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
