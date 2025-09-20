document.addEventListener('DOMContentLoaded', () => {
    // Element references
    const episodeListEl = document.getElementById('episode-list');
    const mainContentContainer = document.getElementById('main-content-container');
    
    // View containers and switcher buttons
    const episodeView = document.getElementById('episode-view');
    const keywordsView = document.getElementById('keywords-view');
    const searchView = document.getElementById('search-view');
    const showEpisodeViewBtn = document.getElementById('show-episode-view');
    const showKeywordsViewBtn = document.getElementById('show-keywords-view');
    const showSearchViewBtn = document.getElementById('show-search-view');

    // Episode Detail elements
    const episodeGridEl = document.getElementById('episode-grid');
    const episodeTitleEl = document.getElementById('episode-title');
    const keywordContainerEl = document.getElementById('keyword-container');
    const transcriptContentEl = document.getElementById('transcript-content');
    const selectedKeywordEl = document.getElementById('selected-keyword');

    // Free text search input
    const freeTextSearchInput = document.getElementById('free-text-search-input');

    // Data stores
    let episodes = {};
    let keywords = {};
    let transcripts = {};
    let episodeFileNames = [];
    let jsonSourceKeywords = new Set(); 

    const getEpisodeNumber = (filename) => parseInt(filename.match(/\d+/)[0]);

    async function fetchData() {
        try {
            const [episodesRes, keywordsRes, transcriptsRes, jsonSourceRes] = await Promise.all([
                fetch('./episode_to_keywords.json'),
                fetch('./keyword_to_episodes.json'),
                fetch('./transcripts.json'),
                fetch('./json_source_keywords.json') 
            ]);
            episodes = await episodesRes.json();
            keywords = await keywordsRes.json();
            transcripts = await transcriptsRes.json();
            jsonSourceKeywords = new Set(await jsonSourceRes.json()); 
            
            episodeFileNames = Object.keys(transcripts).sort((a, b) => {
                return getEpisodeNumber(a) - getEpisodeNumber(b);
            });

            initializeUI();
        } catch (error) {
            console.error("Failed to load data:", error);
            transcriptContentEl.textContent = "Failed to load data. Please check the console for details.";
        }
    }

    function initializeUI() {
        setupViewSwitcher();
        displayEpisodeList(episodeFileNames);
        createEpisodeGrid(episodeFileNames);
        displayGlobalKeywordList(); 
        createTooltip(); // Create the tooltip element on startup

        // Setup free text search input
        let freeTextSearchTimeout;
        freeTextSearchInput.addEventListener('input', (event) => {
            clearTimeout(freeTextSearchTimeout);
            const searchTerm = event.target.value;
            freeTextSearchTimeout = setTimeout(() => {
                if (searchTerm.length >= 2) { 
                    const searchResults = grepTranscripts(searchTerm);
                    renderSearchResults(searchTerm, searchResults);

                    const episodesToHighlight = [...new Set(searchResults.map(r => r.episodeFile))];
                    highlightEpisodes(episodesToHighlight, searchTerm);

                    switchView('search'); 
                }
            }, 300); 
        });
    }

    function setupViewSwitcher() {
        showEpisodeViewBtn.addEventListener('click', () => switchView('episode'));
        showKeywordsViewBtn.addEventListener('click', () => switchView('keywords'));
        showSearchViewBtn.addEventListener('click', () => switchView('search'));
    }

    function switchView(viewName) {
        episodeView.classList.add('hidden');
        keywordsView.classList.add('hidden');
        searchView.classList.add('hidden');
        showEpisodeViewBtn.classList.remove('active');
        showKeywordsViewBtn.classList.remove('active');
        showSearchViewBtn.classList.remove('active');

        if (viewName === 'episode') {
            episodeView.classList.remove('hidden');
            showEpisodeViewBtn.classList.add('active');
        } else if (viewName === 'keywords') {
            keywordsView.classList.remove('hidden');
            showKeywordsViewBtn.classList.add('active');
        } else if (viewName === 'search') {
            searchView.classList.remove('hidden');
            showSearchViewBtn.classList.add('active');
        }
    }

    function displayEpisodeList(episodeNames) {
        episodeListEl.innerHTML = '';
        episodeNames.forEach(episodeName => {
            const li = document.createElement('li');
            const title = transcripts[episodeName]?.title || episodeName;
            li.textContent = title;
            li.dataset.episode = episodeName;
            li.addEventListener('click', () => displayEpisodeDetails(episodeName));
            episodeListEl.appendChild(li);
        });
    }

    function createEpisodeGrid(episodeNames) {
        episodeGridEl.innerHTML = '';
        episodeNames.forEach(episodeName => {
            const cell = document.createElement('div');
            cell.className = 'grid-cell';
            cell.textContent = getEpisodeNumber(episodeName);
            cell.dataset.episode = episodeName;
            cell.addEventListener('click', () => displayEpisodeDetails(episodeName));
            episodeGridEl.appendChild(cell);
        });
    }

    function displayGlobalKeywordList() { 
        keywordsView.innerHTML = ''; // Clear all content

        let keywordsToDisplay = Object.keys(keywords);

        keywordsToDisplay.sort((a, b) => (keywords[b]?.length || 0) - (keywords[a]?.length || 0));

        const keywordListContainer = document.createElement('div');
        keywordListContainer.style.display = 'flex';
        keywordListContainer.style.flexWrap = 'wrap';
        keywordListContainer.style.gap = '5px';

        keywordsToDisplay.forEach(keyword => {
            const keywordEl = createKeywordSpan(keyword);
            keywordEl.style.fontSize = '0.9em'; // Global list has uniform font size
            keywordListContainer.appendChild(keywordEl);
        });
        keywordsView.appendChild(keywordListContainer);
    }

    function createKeywordSpan(keyword) {
        const span = document.createElement('span');
        span.textContent = keyword;
        span.className = 'keyword';
        span.dataset.keyword = keyword;
        span.addEventListener('click', () => handleKeywordClick(keyword));

        const relatedEpisodes = keywords[keyword] || [];
        const coverage = (relatedEpisodes.length / episodeFileNames.length) * 100;
        const hue = 240 - (coverage * 2.4);
        span.style.backgroundColor = `hsl(${hue}, 60%, 50%)`;
        
        if (jsonSourceKeywords.has(keyword)) { 
            span.classList.add('json-source-keyword');
        }

        return span;
    }

    function displayEpisodeDetails(episodeName) {
        switchView('episode');
        mainContentContainer.scrollTop = 0;

        document.querySelectorAll('#episode-list li').forEach(li => {
            li.classList.toggle('active', li.dataset.episode === episodeName);
        });
        document.querySelectorAll('.grid-cell').forEach(cell => {
            cell.classList.toggle('active', cell.dataset.episode === episodeName);
        });

        clearHighlights();

        const episodeData = transcripts[episodeName];
        if (episodeData) {
            episodeTitleEl.textContent = episodeData.title;
            highlightKeywordsInTranscript(episodeData.content);
        } else {
            episodeTitleEl.textContent = episodeName;
            transcriptContentEl.textContent = 'Transcript not found.';
        }
        
        keywordContainerEl.innerHTML = '';
        const episodeKeywords = episodes[episodeName] || [];
        const content = episodeData.content || '';

        const keywordsWithFreq = episodeKeywords.map(keyword => ({
            keyword: keyword,
            frequency: (content.split(keyword).length - 1)
        }));

        const maxFrequency = Math.max(...keywordsWithFreq.map(kw => kw.frequency), 1);

        keywordsWithFreq.sort((a, b) => {
            const countA = keywords[a.keyword]?.length || 0;
            const countB = keywords[b.keyword]?.length || 0;
            return countB - countA;
        });

        keywordsWithFreq.forEach(kwData => {
            const keywordEl = createKeywordSpan(kwData.keyword);

            const baseFontSize = 0.7; // em
            const maxFontSizeIncrement = 1.0; // em
            const fontSize = baseFontSize + (kwData.frequency / maxFrequency) * maxFontSizeIncrement;
            keywordEl.style.fontSize = `${fontSize}em`;

            keywordContainerEl.appendChild(keywordEl);
        });
    }

    function handleKeywordClick(keyword) {
        highlightRelatedEpisodes(keyword);
        const searchResults = grepTranscripts(keyword);
        renderSearchResults(keyword, searchResults);
        switchView('search');
    }

    function highlightEpisodes(episodesToHighlight, title) {
        clearHighlights();
        selectedKeywordEl.textContent = 'None';

        document.querySelectorAll('#episode-list li').forEach(li => {
            if (episodesToHighlight.includes(li.dataset.episode)) {
                li.classList.add('related');
            }
        });
        document.querySelectorAll('.grid-cell').forEach(cell => {
            if (episodesToHighlight.includes(cell.dataset.episode)) {
                cell.classList.add('highlight');
            }
        });
    }

    function highlightRelatedEpisodes(keyword) {
        document.querySelectorAll(`.keyword[data-keyword="${keyword.replace(/"/g, '\"')}"]`).forEach(el => el.classList.add('selected'));
        const relatedEpisodes = keywords[keyword] || [];
        highlightEpisodes(relatedEpisodes, keyword);
    }

    function grepTranscripts(keyword) {
        const results = [];
        for (const filename of episodeFileNames) {
            const transcript = transcripts[filename];
            const lines = transcript.content.split('\n');
            lines.forEach((line, i) => {
                if (line.includes(keyword)) {
                    const beforeLine = i > 0 ? lines[i - 1].trim() : null;
                    const afterLine = i < lines.length - 1 ? lines[i + 1].trim() : null;
                    results.push({
                        episodeFile: filename,
                        episodeTitle: transcript.title, 
                        line: line.trim(),
                        lineNumber: i + 1,
                        beforeLine: beforeLine,
                        afterLine: afterLine
                    });
                }
            });
        }
        return results;
    }

    function renderSearchResults(keyword, results) {
        const resultsContainer = document.getElementById('free-text-search-results');
        resultsContainer.innerHTML = '';
        const header = document.createElement('h2');
        header.textContent = `Search Results for "${keyword}" (${results.length} matches)`;
        resultsContainer.appendChild(header);

        if (results.length === 0) {
            const p = document.createElement('p');
            p.textContent = 'No matches found.';
            resultsContainer.appendChild(p);
            return;
        }

        const groupedResults = new Map();
        results.forEach(result => {
            if (!groupedResults.has(result.episodeTitle)) {
                groupedResults.set(result.episodeTitle, []);
            }
            groupedResults.get(result.episodeTitle).push(result); // Changed from result.line to result
        });

        const escapeRegExp = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const keywordRegex = new RegExp(escapeRegExp(keyword), 'g');

        groupedResults.forEach((episodeResults, episodeTitle) => { // Changed from (lines, episodeTitle) to (episodeResults, episodeTitle)
            const item = document.createElement('div');
            item.className = 'result-item';

            const titleEl = document.createElement('div');
            titleEl.className = 'episode-title';
            titleEl.textContent = episodeTitle;
            item.appendChild(titleEl);

            episodeResults.forEach(result => { // Changed from lines.forEach(line => to episodeResults.forEach(result =>
                const resultBlock = document.createElement('div');
                resultBlock.className = 'result-block';

                if (result.beforeLine) {
                    const beforeEl = document.createElement('div');
                    beforeEl.className = 'line-context before';
                    beforeEl.textContent = result.beforeLine;
                    resultBlock.appendChild(beforeEl);
                }

                const contentEl = document.createElement('div');
                contentEl.className = 'line-content';
                contentEl.innerHTML = result.line.replace(keywordRegex, `<span class="highlight-text">${keyword}</span>`);
                resultBlock.appendChild(contentEl);

                if (result.afterLine) {
                    const afterEl = document.createElement('div');
                    afterEl.className = 'line-context after';
                    afterEl.textContent = result.afterLine;
                    resultBlock.appendChild(afterEl);
                }
                item.appendChild(resultBlock);
            });

            resultsContainer.appendChild(item);
        });
    }

    function clearHighlights() {
        selectedKeywordEl.textContent = 'None';
        document.querySelectorAll('.keyword.selected').forEach(el => el.classList.remove('selected'));
        document.querySelectorAll('#episode-list li.related').forEach(li => li.classList.remove('related'));
        document.querySelectorAll('.grid-cell.highlight').forEach(cell => cell.classList.remove('highlight'));
    }

    function highlightKeywordsInTranscript(content) {
        const allKeywords = Object.keys(keywords);
        allKeywords.sort((a, b) => b.length - a.length);

        if (allKeywords.length === 0) {
            transcriptContentEl.textContent = content;
            return;
        }

        const keywordsRegex = new RegExp(`(${allKeywords.map(kw => kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
        
        const highlightedContent = content.replace(keywordsRegex, (match) => {
            // Find all keywords that are part of the matched string
            const matchingKeywords = allKeywords.filter(kw => match.includes(kw));
            // The longest one will be the first due to the initial sort
            return `<span class="transcript-keyword" data-keywords="${matchingKeywords.join(',')}">${match}</span>`;
        });

        transcriptContentEl.innerHTML = highlightedContent;
    }

    // Event delegation for clicking on highlighted keywords in the transcript
    transcriptContentEl.addEventListener('click', (event) => {
        if (event.target.classList.contains('transcript-keyword')) {
            const keywordsAttr = event.target.dataset.keywords;
            if (keywordsAttr) {
                const longestKeyword = keywordsAttr.split(',')[0];
                handleKeywordClick(longestKeyword);
            }
        }
    });

    // --- Tooltip Implementation ---
    let tooltipEl;
    function createTooltip() {
        tooltipEl = document.createElement('div');
        tooltipEl.id = 'transcript-tooltip';
        tooltipEl.className = 'hidden';
        document.body.appendChild(tooltipEl);
    }

    transcriptContentEl.addEventListener('mouseover', (event) => {
        if (event.target.classList.contains('transcript-keyword')) {
            const keywordsAttr = event.target.dataset.keywords;
            if (keywordsAttr) {
                const keywordsList = keywordsAttr.split(',');
                const formattedKeywords = keywordsList.map(kw => {
                    const episodeCount = keywords[kw] ? keywords[kw].length : 0;
                    return `${kw} (${episodeCount})`;
                });
                tooltipEl.innerHTML = formattedKeywords.join('<br>');
                tooltipEl.classList.remove('hidden');

                // Position the tooltip below the keyword
                const rect = event.target.getBoundingClientRect();
                tooltipEl.style.left = `${window.scrollX + rect.left}px`;
                tooltipEl.style.top = `${window.scrollY + rect.bottom + 5}px`;
            }
        }
    });

    transcriptContentEl.addEventListener('mouseout', (event) => {
        if (event.target.classList.contains('transcript-keyword')) {
            tooltipEl.classList.add('hidden');
        }
    });

    fetchData();
});