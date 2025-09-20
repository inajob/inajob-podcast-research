
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


class ShiftReduceParser:
    def __init__(self, debug_mode=False):
        """
        文法ルールを初期化する。
        ルールは (左辺の記号, [右辺の記号のリスト]) のタプルで定義。
        ルールの順序が重要。長いルールや優先度の高いルールを先に書く。
        """
        self.rules = [
            # --- 名詞句 (NP) を生成するルール ---
            ('NP', ['NP', 'P_attr', 'NP']),   # Rule A
            ('NP', ['VP', 'NP']),             # Rule G/H
            ('NP', ['MOD', 'NP']),            # Rule B
            ('NP', ['NP', 'P_para', 'NP']),   # Rule E

            # --- 動詞句 (VP) を生成するルール ---
            ('VP', ['NP', 'P_obj', 'VP']),   # Rule C
            ('VP', ['VP', 'P_conn', 'VP']),   # Rule I
            ('VP', ['MOD', 'VP']),            # Rule B
            ('VP', ['NP', 'P_subj', 'VP']),   # Rule D

            # --- 形容詞句 (ADJP) を生成するルール ---
            ('ADJP', ['NP', 'P_subj', 'ADJP']), # Rule D
            ('ADJP', ['MOD', 'ADJP']),          # Rule B

            # --- 節 (Clause) を生成するルール ---
            ('Clause', ['ADJP', 'P_reason', 'VP']), # Rule F (代表例)
        ]
        self.debug_mode = debug_mode

    def _find_rule_match(self, stack):
        """
        スタックの末尾が、いずれかのルールの右辺にマッチするかどうかをチェックする。
        マッチすれば、そのルールとマッチした長さを返す。
        """
        for lhs, rhs in self.rules:
            rhs_len = len(rhs)
            if len(stack) >= rhs_len:
                stack_end_pos = [chunk['pos'] for chunk in stack[-rhs_len:]]
                if stack_end_pos == rhs:
                    return (lhs, rhs), rhs_len
        return None, 0

    def parse(self, chunks):
        """
        シフトリデュース構文解析を実行する。
        """
        stack = []
        queue = list(chunks)

        if self.debug_mode:
            print(f"--- 解析開始 ---")
            print(f"入力キュー: {[c['surface'] for c in queue]}")

        while queue or len(stack) > 1:
            reduced_in_pass = False
            while True:
                rule, rhs_len = self._find_rule_match(stack)
                if rule:
                    lhs, rhs = rule
                    target_chunks = stack[-rhs_len:]
                    combined_surface = "".join([c['surface'] for c in target_chunks])
                    
                    if self.debug_mode:
                        print(f"リデュース実行: {' '.join([c['surface'] for c in target_chunks])}  ->  {lhs}('{combined_surface}')")

                    stack = stack[:-rhs_len]
                    new_chunk = {'pos': lhs, 'surface': combined_surface, 'from': rhs, 'children': target_chunks}
                    stack.append(new_chunk)
                    reduced_in_pass = True
                else:
                    break
            
            if queue:
                chunk_to_shift = queue.pop(0)
                if self.debug_mode:
                    print(f"シフト: '{chunk_to_shift['surface']}' ({chunk_to_shift['pos']})")
                stack.append(chunk_to_shift)
            
            elif not reduced_in_pass and len(stack) > 1:
                if self.debug_mode:
                    print(f"解析失敗: キューが空ですが、スタックを1つの句にリデュースできません。")
                    print(f"最終スタック: {json.dumps(stack, indent=2, ensure_ascii=False)}")
                return stack

        if self.debug_mode:
            print(f"--- 解析完了 ---")
        return stack

    def _collect_chunks_from_tree(self, root_chunk):
        """
        解析結果の木構造を再帰的に辿り、すべての中間生成物を含むチャンクをリストで返す。
        """
        if not root_chunk:
            return []
        
        collected = [root_chunk]
        if 'children' in root_chunk:
            for child in root_chunk['children']:
                collected.extend(self._collect_chunks_from_tree(child))
        return collected

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

print("Tokenizing transcripts (using cache possible)...")
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

def create_base_chunks(tokens):
    chunks = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        pos_major = token['part_of_speech'].split(',')[0]
        pos_minor = token['part_of_speech'].split(',')[1]

        # Rule 1: Noun Phrases (NP)
        if pos_major == '接頭詞' or pos_major == '名詞':
            j = i
            chunk_tokens = []
            while j < len(tokens):
                current_pos_major = tokens[j]['part_of_speech'].split(',')[0]
                if current_pos_major == '名詞' or current_pos_major == '接頭詞':
                    chunk_tokens.append(tokens[j])
                    j += 1
                else:
                    break
            if chunk_tokens:
                chunks.append({
                    'surface': "".join([t['surface'] for t in chunk_tokens]),
                    'tokens': chunk_tokens,
                    'pos': 'NP'
                })
                i = j
                continue

        # Rule 2: Verb Phrases (VP)
        if pos_major == '動詞':
            j = i
            chunk_tokens = [tokens[j]]
            j += 1
            while j < len(tokens):
                current_pos_major = tokens[j]['part_of_speech'].split(',')[0]
                if current_pos_major == '助動詞':
                    chunk_tokens.append(tokens[j])
                    j += 1
                else:
                    break
            chunks.append({
                'surface': "".join([t['surface'] for t in chunk_tokens]),
                'tokens': chunk_tokens,
                'pos': 'VP'
            })
            i = j
            continue

        # Rule 3: Adjective Phrases (ADJP) & Modifiers (MOD)
        if pos_major in ['形容詞', '形容動詞', '副詞', '連体詞']:
            pos_map = {
                '形容詞': 'ADJP',
                '形容動詞': 'ADJP',
                '副詞': 'MOD',
                '連体詞': 'MOD'
            }
            chunks.append({
                'surface': token['surface'],
                'tokens': [token],
                'pos': pos_map.get(pos_major)
            })
            i += 1
            continue

        # Rule 4: Particles (P_*)
        if pos_major == '助詞':
            new_pos = 'P' # Default Particle
            surface = token['surface']
            if pos_minor == '連体化':
                new_pos = 'P_attr'
            elif pos_minor == '格助詞' and surface == 'を':
                new_pos = 'P_obj'
            elif (pos_minor == '格助詞' or pos_minor == '係助詞') and surface in ['が', 'は']:
                new_pos = 'P_subj'
            elif pos_minor == '接続助詞':
                new_pos = 'P_conn'
            elif pos_minor == '並立助詞':
                new_pos = 'P_para'
            elif surface in ['ので', 'から']:
                new_pos = 'P_reason'
            
            chunks.append({
                'surface': surface,
                'tokens': [token],
                'pos': new_pos
            })
            i += 1
            continue

        # Default Rule (その他)
        chunks.append({
            'surface': token['surface'],
            'tokens': [token],
            'pos': pos_major # その他の品詞はそのまま (例: '記号')
        })
        i += 1
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
                if chunk_pos != 'NP': # Updated from '名詞' to 'NP'
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

# 3. Generate keywords from tokens using the new ShiftReduceParser
print("Generating keywords using Shift-Reduce Parser...")

file_counter = 0 # デバッグ用カウンタ

all_generated_chunks = defaultdict(set)

for filename, tokens in all_tokens.items():
    debug_this_file = False # 最初の1ファイルだけデバッグモード
    parser = ShiftReduceParser(debug_mode=debug_this_file)
    file_counter += 1

    base_chunks = create_base_chunks(tokens)
    if debug_this_file:
        print(f"--- Base Chunks for {filename} ---")
        for chunk in base_chunks:
            print(f"  Surface: '{chunk['surface']}', POS: '{chunk['pos']}'")
        print(f"--- End Base Chunks ---")
    
    # パーサーで構文解析を実行
    final_stack = parser.parse(base_chunks)

    # 最終スタック内のすべてのチャンクからキーワード候補を収集
    for chunk in final_stack:
        all_sub_chunks = parser._collect_chunks_from_tree(chunk)
        for sub_chunk in all_sub_chunks:
            # 意味のある句（NP, VP, ADJP）のみをキーワード候補とする
            if sub_chunk.get('pos') in ['NP', 'VP', 'ADJP'] and len(sub_chunk['surface']) > 1:
                all_generated_chunks[sub_chunk['surface']].add(sub_chunk['pos'])

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
