(async function() {
    const errorDiv = document.getElementById('db-error-message');
    const waiverContainer = document.getElementById('waiver-players-container');
    const freeAgentContainer = document.getElementById('free-agent-players-container');
    const playerSearchInput = document.getElementById('player-search');
    const checkboxesContainer = document.getElementById('category-checkboxes-container');
    const recalculateButton = document.getElementById('recalculate-button');
    const unusedRosterSpotsContainer = document.getElementById('unused-roster-spots-container');
    const timestampText = document.getElementById('available-players-timestamp-text');

    // --- Caching Configuration ---
    const CACHE_KEY = 'freeAgentsCache';
    const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

    // --- Global State ---
    let allWaiverPlayers = [];
    let allFreeAgents = [];
    let allScoringCategories = [];
    let rankedCategories = [];
    let checkedCategories = [];
    let sortConfig = {
        waivers: { key: 'total_cat_rank', direction: 'ascending' },
        freeAgents: { key: 'total_cat_rank', direction: 'ascending' }
    };

    // --- Caching Functions ---
    function saveStateToCache() {
        try {
            const state = {
                allWaiverPlayers,
                allFreeAgents,
                allScoringCategories,
                rankedCategories,
                checkedCategories,
                sortConfig,
                unusedRosterSpotsHTML: unusedRosterSpotsContainer.innerHTML,
                selectedTeam: document.getElementById('your-team-select')?.value,
                searchTerm: playerSearchInput.value,
                timestamp: Date.now()
            };
            localStorage.setItem(CACHE_KEY, JSON.stringify(state));
        } catch (error) {
            console.warn("Could not save state to local storage.", error);
        }
    }

    function loadStateFromCache() {
        try {
            const cachedJSON = localStorage.getItem(CACHE_KEY);
            if (!cachedJSON) return null;

            const cachedState = JSON.parse(cachedJSON);
            if (Date.now() - cachedState.timestamp > CACHE_TTL_MS) {
                localStorage.removeItem(CACHE_KEY);
                return null;
            }
            return cachedState;
        } catch (error) {
            console.warn("Could not load state from local storage.", error);
            return null;
        }
    }

    function getHeatmapColor(rank) {
        if (rank === null || rank === undefined || rank === '-') return '';
        const minRank = 1, maxRank = 20;
        const clampedRank = Math.max(minRank, Math.min(rank, maxRank));
        const percentage = (clampedRank - minRank) / (maxRank - minRank);
        const hue = (1 - percentage) * 120;
        return `hsl(${hue}, 65%, 75%)`;
    }

    async function getTimestamp() {
        if (!timestampText) return;
        try {
            const response = await fetch('/api/available_players_timestamp');
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to fetch timestamp.');
            }

            if (data.timestamp) {
                timestampText.textContent = `Available player data was last refreshed at: ${data.timestamp}`;
            } else {
                timestampText.textContent = 'Available player data has not been updated. Please run an update from the League Database page.';
            }
        } catch (error) {
            console.error('Error setting timestamp:', error);
            timestampText.textContent = 'Could not load data status.';
        }
    }

    async function fetchData(selectedCategories = null) {
        waiverContainer.innerHTML = '<p class="text-gray-400">Loading waiver players...</p>';
        freeAgentContainer.innerHTML = '<p class="text-gray-400">Loading free agents...</p>';
        unusedRosterSpotsContainer.innerHTML = '<p class="text-gray-400">Loading unused spots...</p>';
        const yourTeamSelect = document.getElementById('your-team-select');
        const selectedTeam = yourTeamSelect ? yourTeamSelect.value : null;

        try {
            const payload = { team_name: selectedTeam };
            if (selectedCategories) {
                payload.categories = selectedCategories;
            }

            const response = await fetch('/api/free_agent_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json();

            if (!response.ok) throw new Error(data.error || 'Failed to fetch free agent data.');

            allWaiverPlayers = data.waiver_players;
            allFreeAgents = data.free_agents;
            rankedCategories = data.ranked_categories;
            checkedCategories = data.checked_categories || data.ranked_categories;

            if (allScoringCategories.length === 0 && data.scoring_categories) {
                allScoringCategories = data.scoring_categories;
                renderCategoryCheckboxes();
            } else if (allScoringCategories.length > 0) {
                renderCategoryCheckboxes();
            }

            renderUnusedRosterSpotsTable(data.unused_roster_spots);
            filterAndSortPlayers();
            saveStateToCache();

        } catch (error) {
            console.error('Fetch error:', error);
            errorDiv.textContent = `Error: ${error.message}`;
            errorDiv.classList.remove('hidden');
            waiverContainer.innerHTML = '';
            freeAgentContainer.innerHTML = '';
            unusedRosterSpotsContainer.innerHTML = '';
        }
    }

    /**
     * MODIFIED FUNCTION
     * Adds Check All and Uncheck All buttons
     */
    function renderCategoryCheckboxes() {
        let checkboxHtml = `
            <div class="flex justify-between items-center mb-2">
                <label class="block text-sm font-medium text-gray-300">Recalculate Rank Based On:</label>
                <div>
                    <button id="check-all-btn" class="text-xs bg-gray-600 hover:bg-gray-500 text-white py-1 px-2 rounded mr-2 transition-colors duration-150">Check All</button>
                    <button id="uncheck-all-btn" class="text-xs bg-gray-600 hover:bg-gray-500 text-white py-1 px-2 rounded transition-colors duration-150">Uncheck All</button>
                </div>
            </div>
            <div class="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
        `;
        allScoringCategories.forEach(cat => {
            const isChecked = checkedCategories.includes(cat);
            checkboxHtml += `
                <div class="flex items-center">
                    <input id="cat-${cat}" name="category" type="checkbox" value="${cat}" ${isChecked ? 'checked' : ''} class="h-4 w-4 bg-gray-700 border-gray-600 text-indigo-600 focus:ring-indigo-500 rounded">
                    <label for="cat-${cat}" class="ml-2 block text-sm text-gray-300">${cat}</label>
                </div>
            `;
        });
        checkboxHtml += '</div>';
        checkboxesContainer.innerHTML = checkboxHtml;
    }

    function filterAndSortPlayers() {
        const searchTerm = playerSearchInput.value.toLowerCase();

        let filteredWaivers = searchTerm ? allWaiverPlayers.filter(p => p.player_name.toLowerCase().includes(searchTerm)) : [...allWaiverPlayers];
        sortPlayers(filteredWaivers, sortConfig.waivers);
        renderPlayerTable('Waiver Players', filteredWaivers, waiverContainer, 'waivers');

        let filteredFreeAgents = searchTerm ? allFreeAgents.filter(p => p.player_name.toLowerCase().includes(searchTerm)) : [...allFreeAgents];
        sortPlayers(filteredFreeAgents, sortConfig.freeAgents);
        renderPlayerTable('Free Agents', filteredFreeAgents, freeAgentContainer, 'freeAgents', true);
    }

    function sortPlayers(players, config) {
        players.sort((a, b) => {
            let valA = a[config.key] === 0 ? Infinity : a[config.key];
            let valB = b[config.key] === 0 ? Infinity : b[config.key];
            if (config.key === 'player_name') {
                valA = String(a.player_name).toLowerCase();
                valB = String(b.player_name).toLowerCase();
            }
            if (valA < valB) return config.direction === 'ascending' ? -1 : 1;
            if (valA > valB) return config.direction === 'ascending' ? 1 : -1;
            return 0;
        });
    }

    function renderPlayerTable(title, players, container, tableType, shouldCap = false) {
        if (!players) {
            container.innerHTML = `<h2 class="text-2xl font-bold text-white mb-3">${title}</h2><p class="text-gray-400">No players found.</p>`;
            return;
        }
        const playersToDisplay = shouldCap ? players.slice(0, 100) : players;
        let tableHtml = `
            <div class="bg-gray-900 rounded-lg shadow">
                <h2 class="text-2xl font-bold text-white p-4 bg-gray-800 rounded-t-lg">${title}</h2>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead class="bg-gray-700/50">
                            <tr>
                                <th class="px-2 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider sortable" data-sort-key="player_name" data-table-type="${tableType}">Player Name</th>
                                <th class="px-2 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Team</th>
                                <th class="px-2 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Positions</th>
                                <th class="px-2 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">This Week</th>
                                <th class="px-2 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Next Week</th>
                                <th class="px-2 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider sortable" data-sort-key="total_cat_rank" data-table-type="${tableType}">Total Cat Rank</th>
        `;
        rankedCategories.forEach(cat => {
            const isChecked = checkedCategories.includes(cat);
            const headerText = isChecked ? cat : `${cat}*`;
            tableHtml += `<th class="px-2 py-2 text-center text-xs font-bold text-gray-300 uppercase tracking-wider sortable" data-sort-key="${cat}_cat_rank" data-table-type="${tableType}">${headerText}</th>`;
        });
        tableHtml += `
                            </tr>
                            <tr><td colspan="${6 + rankedCategories.length}" class="text-center text-xs text-gray-500 py-1">Click headers to sort</td></tr>
                        </thead>
                        <tbody class="bg-gray-800 divide-y divide-gray-700">
        `;
        if (playersToDisplay.length === 0) {
            tableHtml += `<tr><td colspan="${6 + rankedCategories.length}" class="text-center py-4">No players match the current filter.</td></tr>`;
        } else {
            playersToDisplay.forEach(player => {
                tableHtml += `
                    <tr class="hover:bg-gray-700/50">
                        <td class="px-2 py-2 whitespace-nowrap text-sm font-medium text-gray-300">${player.player_name}</td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm text-gray-300">${player.player_team}</td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm text-gray-300">${player.positions}</td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm text-gray-300">${(player.games_this_week || []).join(', ')}</td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm text-gray-300">${(player.games_next_week || []).join(', ')}</td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm font-bold text-yellow-300">${player.total_cat_rank}</td>
                `;
                rankedCategories.forEach(cat => {
                    const rankKey = `${cat}_cat_rank`;
                    const rank = (player[rankKey] !== null && player[rankKey] !== undefined) ? player[rankKey].toFixed(2) : '-';
                    const color = getHeatmapColor(rank);
                    tableHtml += `<td class="px-2 py-1 whitespace-nowrap text-sm text-center font-semibold text-gray-800" style="background-color: ${color};">${rank}</td>`;
                });
                tableHtml += `</tr>`;
            });
        }
        tableHtml += `</tbody></table></div></div>`;
        container.innerHTML = tableHtml;
        document.querySelectorAll(`[data-table-type="${tableType}"].sortable`).forEach(header => {
            header.classList.remove('sort-asc', 'sort-desc');
            if (header.dataset.sortKey === sortConfig[tableType].key) {
                header.classList.add(sortConfig[tableType].direction === 'ascending' ? 'sort-asc' : 'sort-desc');
            }
            header.removeEventListener('click', handleSortClick);
            header.addEventListener('click', handleSortClick);
        });
    }

    function handleSortClick(e) {
        const key = e.target.dataset.sortKey;
        const tableType = e.target.dataset.tableType;
        if (sortConfig[tableType].key === key) {
            sortConfig[tableType].direction = sortConfig[tableType].direction === 'ascending' ? 'descending' : 'ascending';
        } else {
            sortConfig[tableType].key = key;
            sortConfig[tableType].direction = 'ascending';
        }
        filterAndSortPlayers();
        saveStateToCache();
    }

    function handleRecalculateClick() {
        const selectedCategories = Array.from(document.querySelectorAll('#category-checkboxes-container input:checked')).map(cb => cb.value);
        fetchData(selectedCategories);
    }

    function renderUnusedRosterSpotsTable(unusedSpotsData) {
        if (!unusedSpotsData) {
            unusedRosterSpotsContainer.innerHTML = '';
            return;
        }
        const positionOrder = ['C', 'LW', 'RW', 'D', 'G'];
        const dayOrder = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        const sortedDays = Object.keys(unusedSpotsData).sort((a, b) => dayOrder.indexOf(a) - dayOrder.indexOf(b));
        let tableHtml = `
            <div class="bg-gray-900 rounded-lg shadow">
                <h2 class="text-xl font-bold text-white p-3 bg-gray-800 rounded-t-lg">Unused Roster Spots</h2>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead class="bg-gray-700/50">
                            <tr>
                                <th class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Day</th>
                                ${positionOrder.map(pos => `<th class="px-2 py-1 text-center text-xs font-bold text-gray-300 uppercase tracking-wider">${pos}</th>`).join('')}
                            </tr>
                        </thead>
                        <tbody class="bg-gray-800 divide-y divide-gray-700">
        `;
        sortedDays.forEach(day => {
            tableHtml += `<tr class="hover:bg-gray-700/50">
                <td class="px-2 py-1 whitespace-nowrap text-sm font-medium text-gray-300">${day}</td>`;
            positionOrder.forEach(pos => {
            const value = unusedSpotsData[day][pos];
            const stringValue = String(value);

            const highlightClass = (stringValue !== '0')
                ? 'bg-green-200 text-gray-900'
                : 'text-gray-300';

                tableHtml += `<td class="px-2 py-1 whitespace-nowrap text-sm text-center ${highlightClass}">${value}</td>`;
            });
            tableHtml += `</tr>`;
        });
        tableHtml += `</tbody></table></div></div>`;
        unusedRosterSpotsContainer.innerHTML = tableHtml;
    }

    /**
     * MODIFIED FUNCTION
     * Adds event delegation for the new Check All/Uncheck All buttons.
     */
    function setupEventListeners() {
        playerSearchInput.addEventListener('input', () => {
            filterAndSortPlayers();
            saveStateToCache();
        });
        recalculateButton.addEventListener('click', handleRecalculateClick);

        // Event delegation for dynamically added category buttons
        checkboxesContainer.addEventListener('click', (e) => {
            const setAllCheckboxes = (checkedState) => {
                const checkboxes = checkboxesContainer.querySelectorAll('input[name="category"]');
                checkboxes.forEach(cb => {
                    cb.checked = checkedState;
                });
            };

            if (e.target.id === 'check-all-btn') {
                setAllCheckboxes(true);
            } else if (e.target.id === 'uncheck-all-btn') {
                setAllCheckboxes(false);
            }
        });

        const yourTeamSelect = document.getElementById('your-team-select');
        if (yourTeamSelect) {
            yourTeamSelect.addEventListener('change', () => {
                const selectedCategories = Array.from(document.querySelectorAll('#category-checkboxes-container input:checked')).map(cb => cb.value);
                fetchData(selectedCategories);
            });
        }
    }

    // --- Initial Load ---
    async function init() {
        await getTimestamp(); // Fetch timestamp on initial load
        const cachedState = loadStateFromCache();
        if (cachedState) {
            console.log("Loading Free Agents page from cache.");
            allWaiverPlayers = cachedState.allWaiverPlayers;
            allFreeAgents = cachedState.allFreeAgents;
            allScoringCategories = cachedState.allScoringCategories;
            rankedCategories = cachedState.rankedCategories;
            checkedCategories = cachedState.checkedCategories;
            sortConfig = cachedState.sortConfig;

            await new Promise(resolve => setTimeout(resolve, 0)); // Ensure DOM is ready for value setting

            if (cachedState.selectedTeam) {
                const teamSelect = document.getElementById('your-team-select');
                if (teamSelect) teamSelect.value = cachedState.selectedTeam;
            }
            playerSearchInput.value = cachedState.searchTerm;
            unusedRosterSpotsContainer.innerHTML = cachedState.unusedRosterSpotsHTML;

            renderCategoryCheckboxes();
            filterAndSortPlayers();
            setupEventListeners();
        } else {
            console.log("No valid cache. Fetching fresh data for Free Agents page.");
            setupEventListeners();
            fetchData();
        }
    }

    init();
})();
