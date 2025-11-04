(async function() {
    const errorDiv = document.getElementById('db-error-message');
    const waiverContainer = document.getElementById('waiver-players-container');
    const freeAgentContainer = document.getElementById('free-agent-players-container');
    const playerSearchInput = document.getElementById('player-search');
    const checkboxesContainer = document.getElementById('category-checkboxes-container');
    const positionFiltersContainer = document.getElementById('position-filters-container');
    const dayFiltersContainer = document.getElementById('day-filters-container');
    const recalculateButton = document.getElementById('recalculate-button');
    const unusedRosterSpotsContainer = document.getElementById('unused-roster-spots-container');
    const timestampText = document.getElementById('available-players-timestamp-text');
    // --- NEW UI Elements ---
    const playerDropDropdown = document.getElementById('player-drop-dropdown');
    const transactionDatePicker = document.getElementById('transaction-date-picker');
    const simulateButton = document.getElementById('simulate-add-drop-button');
    const resetButton = document.getElementById('reset-add-drops-button');
    const simLogContainer = document.getElementById('simulated-moves-log');

    // --- Caching Configuration ---
    const CACHE_KEY = 'freeAgentsCache';
    const SIMULATION_KEY = 'simulationCache';

    // --- Global State ---
    let allWaiverPlayers = [];
    let allFreeAgents = [];
    let allScoringCategories = [];
    let rankedCategories = [];
    let checkedCategories = [];
    let selectedPositions = [];
    let selectedDays = [];
    let currentUnusedSpots = null;
    let currentTeamRoster = [];
    let currentWeekDates = [];
    let simulatedMoves = [];
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
                selectedPositions,
                selectedDays,
                sortConfig,
                unusedRosterSpotsHTML: unusedRosterSpotsContainer.innerHTML,
                unusedRosterSpotsData: currentUnusedSpots,
                currentTeamRoster: currentTeamRoster,
                currentWeekDates: currentWeekDates,
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
            // --- NEW: Load simulation from its own key ---
            const cachedSim = localStorage.getItem(SIMULATION_KEY);
            simulatedMoves = cachedSim ? JSON.parse(cachedSim) : [];

            const cachedJSON = localStorage.getItem(CACHE_KEY);
            if (!cachedJSON) return null;

            const cachedState = JSON.parse(cachedJSON);
            // Set a shorter cache time now that we have complex state
            const CACHE_TTL_MS = 2 * 60 * 1000; // 2 minutes
            if (Date.now() - cachedState.timestamp > CACHE_TTL_MS) {
                localStorage.removeItem(CACHE_KEY);
                return null;
            }
            currentUnusedSpots = cachedState.unusedRosterSpotsData;
            currentTeamRoster = cachedState.currentTeamRoster || [];
            currentWeekDates = cachedState.currentWeekDates || [];
            selectedPositions = cachedState.selectedPositions || [];
            selectedDays = cachedState.selectedDays || [];
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
            // --- [START] FIX #1 ---
            // Add the global simulatedMoves array to the payload
            const payload = {
                team_name: selectedTeam,
                simulated_moves: simulatedMoves
            };
            // --- [END] FIX #1 ---

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
            currentUnusedSpots = data.unused_roster_spots;
            currentTeamRoster = data.team_roster;
            currentWeekDates = data.week_dates;


            if (allScoringCategories.length === 0 && data.scoring_categories) {
                allScoringCategories = data.scoring_categories;
                renderCategoryCheckboxes();
            } else if (allScoringCategories.length > 0) {
                renderCategoryCheckboxes();
            }
            renderPositionFilters();
            renderDayFilters();
            // --- NEW: Populate new UI elements ---
            populateDropPlayerDropdown();
            populateTransactionDatePicker(currentWeekDates);
            renderSimulatedMovesLog();
            renderUnusedRosterSpotsTable(currentUnusedSpots);
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

    function renderPositionFilters() {
            const POSITIONS = ['C', 'LW', 'RW', 'D', 'G'];
            let filterHtml = '';
            POSITIONS.forEach(pos => {
                const isChecked = selectedPositions.includes(pos);
                filterHtml += `
                    <div class="flex items-center">
                        <input id="pos-${pos}" name="position-filter" type="checkbox" value="${pos}" ${isChecked ? 'checked' : ''} class="h-4 w-4 bg-gray-700 border-gray-600 text-indigo-600 focus:ring-indigo-500 rounded">
                        <label for="pos-${pos}" class="ml-2 text-sm text-gray-300">${pos}</label>
                    </div>
                `;
            });
            positionFiltersContainer.innerHTML = filterHtml;
        }

    function renderDayFilters() {
            const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
            let filterHtml = '';
            DAYS.forEach(day => {
                const isChecked = selectedDays.includes(day);
                filterHtml += `
                    <div class="flex items-center">
                        <input id="day-${day}" name="day-filter" type="checkbox" value="${day}" ${isChecked ? 'checked' : ''} class="h-4 w-4 bg-gray-700 border-gray-600 text-indigo-500 focus:ring-indigo-500 rounded">
                        <label for="day-${day}" class="ml-2 text-sm text-gray-300">${day}</label>
                    </div>
                `;
            });
            dayFiltersContainer.innerHTML = filterHtml;
        }

    function filterAndSortPlayers() {
            const searchTerm = playerSearchInput.value.toLowerCase();

            // Read selected positions from the checkboxes
            selectedPositions = Array.from(document.querySelectorAll('#position-filters-container input:checked')).map(cb => cb.value);

            // Read selected days from the checkboxes
            selectedDays = Array.from(document.querySelectorAll('#day-filters-container input:checked')).map(cb => cb.value);

            const positionFilter = (player) => {
                // If no positions are selected, show all players
                if (selectedPositions.length === 0) {
                    return true;
                }
                // If positions are selected, check if the player's position string contains ANY of them (OR logic)
                const playerPositions = player.positions || '';
                return selectedPositions.some(pos => playerPositions.includes(pos));
            };

            // Day filter with AND logic
            const dayFilter = (player) => {
                // If no days are selected, show all players
                if (selectedDays.length === 0) {
                    return true;
                }
                // Check if the player has games on ALL selected days (AND logic)
                const playerGames = player.games_this_week || [];
                return selectedDays.every(day => playerGames.includes(day));
            };

            const searchFilter = (player) => {
                return player.player_name.toLowerCase().includes(searchTerm);
            };

            // Apply all three filters
            let filteredWaivers = allWaiverPlayers.filter(p => searchFilter(p) && positionFilter(p) && dayFilter(p));
            sortPlayers(filteredWaivers, sortConfig.waivers);
            renderPlayerTable('Waiver Players', filteredWaivers, waiverContainer, 'waivers');

            let filteredFreeAgents = allFreeAgents.filter(p => searchFilter(p) && positionFilter(p) && dayFilter(p));
            sortPlayers(filteredFreeAgents, sortConfig.freeAgents);
            renderPlayerTable('Free Agents', filteredFreeAgents, freeAgentContainer, 'freeAgents', true);
        }

    function sortPlayers(players, config) {
        // Helper to get the value, treating null/undefined/0/- as the highest (Infinity)
        const getSortableValue = (value) => {
            if (value === null || value === undefined || value === 0 || value === '-') {
                return Infinity;
            }
            return value;
        };

        players.sort((a, b) => {
            let valA, valB;

            if (config.key === 'player_name') {
                valA = String(a.player_name).toLowerCase();
                valB = String(b.player_name).toLowerCase();
            } else {
                valA = getSortableValue(a[config.key]);
                valB = getSortableValue(b[config.key]);
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
                                <th class="px-2 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Add</th>
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
                            <tr><td colspan="${7 + rankedCategories.length}" class="text-center text-xs text-gray-500 py-1">Click headers to sort</td></tr>
                        </thead>
                        <tbody class="bg-gray-800 divide-y divide-gray-700">
        `;
        if (playersToDisplay.length === 0) {
            tableHtml += `<tr><td colspan="${7 + rankedCategories.length}" class="text-center py-4">No players match the current filter.</td></tr>`;
        } else {
            playersToDisplay.forEach(player => {

                // --- NEW: Check if player is already in sim moves ---
                const isAlreadyAdded = simulatedMoves.some(m => m.added_player.player_id === player.player_id);
                const checkboxDisabled = isAlreadyAdded ? 'disabled' : '';

                // --- NEW LOGIC for This Week Highlighting ---
                let gamesThisWeekHtml = '';
                const playerPositions = player.positions ? player.positions.split(',') : [];
                const gamesThisWeek = player.games_this_week || [];

                if (!currentUnusedSpots || playerPositions.length === 0) {
                    gamesThisWeekHtml = gamesThisWeek.join(', ');
                } else {
                    gamesThisWeekHtml = gamesThisWeek.map(day => {
                        const dailySpots = currentUnusedSpots[day];
                        if (!dailySpots) {
                            return day; // No spot data for this day
                        }

                        for (const pos of playerPositions) {
                            const trimmedPos = pos.trim();
                            if (dailySpots.hasOwnProperty(trimmedPos)) {
                                const spotValue = String(dailySpots[trimmedPos]);
                                if (spotValue !== '0') {
                                    return `<strong class="text-yellow-300">${day}</strong>`;
                                }
                            }
                        }
                        return day; // No open spot found for this player's positions
                    }).join(', ');
                }
                // --- END NEW LOGIC ---

                tableHtml += `
                    <tr class="hover:bg-gray-700/50">
                        <td class="px-2 py-2 whitespace-nowrap text-sm text-center">
                            <input type="checkbox" name="player-to-add" class="h-4 w-4 bg-gray-700 border-gray-600 text-indigo-600 focus:ring-indigo-500 rounded"
                                   value="${player.player_id}" data-table="${tableType}" ${checkboxDisabled}>
                        </td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm font-medium text-gray-300">${player.player_name}</td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm text-gray-300">${player.player_team}</td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm text-gray-300">${player.positions}</td>
                        <td class="px-2 py-2 whitespace-nowrap text-sm text-gray-300">${gamesThisWeekHtml}</td>
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

        sortConfig[tableType].key = key;
        sortConfig[tableType].direction = 'ascending';

        filterAndSortPlayers();
        saveStateToCache();
    }

    function handleRecalculateClick() {
        const selectedCategories = Array.from(document.querySelectorAll('#category-checkboxes-container input:checked')).map(cb => cb.value);
        fetchData(selectedCategories);
    }

    // --- NEW SIMULATION FUNCTIONS ---

    function populateDropPlayerDropdown() {
            // Create a set of player IDs that have been dropped in the simulation
            const droppedPlayerIds = new Set(simulatedMoves.map(m => m.dropped_player.player_id));

            let optionsHtml = '<option selected value="">Select player to drop...</option>';

            // Add players from the original roster
            currentTeamRoster.forEach(player => {
                // Only add if they haven't been dropped
                if (!droppedPlayerIds.has(player.player_id)) {
                    optionsHtml += `<option value="${player.player_id}" data-type="roster">${player.player_name} - ${player.eligible_positions}</option>`;
                }
            });

            // Add players from the simulation
            simulatedMoves.forEach(move => {
                const player = move.added_player;
                // --- NEW: Only add if they haven't been subsequently dropped ---
                if (!droppedPlayerIds.has(player.player_id)) {
                    optionsHtml += `<option value="${player.player_id}" data-type="simulated" data-add-date="${move.date}">
                        ${player.player_name} - ${player.positions} (Added ${move.date})
                    </option>`;
                }
            });

            playerDropDropdown.innerHTML = optionsHtml;
        }

    function populateTransactionDatePicker(dates) {
        let optionsHtml = '<option selected value="">Select date...</option>';
        dates.forEach(date => {
            optionsHtml += `<option value="${date}">${date}</option>`;
        });
        transactionDatePicker.innerHTML = optionsHtml;
    }

    function renderSimulatedMovesLog() {
        if (simulatedMoves.length === 0) {
            simLogContainer.innerHTML = ''; // Clear the container if no moves
            return;
        }

        const sortedMoves = [...simulatedMoves].sort((a, b) => {
            if (a.date < b.date) return -1;
            if (a.date > b.date) return 1;
            return 0;
        });

        let logHtml = `
            <h4 class="text-lg font-semibold text-white mt-6 mb-2">Simulated Moves Log</h4>
            <div class="overflow-x-auto bg-gray-800 rounded-lg shadow">
                <table class="min-w-full divide-y divide-gray-700">
                    <thead class="bg-gray-700/50">
                        <tr>
                            <th class="px-3 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Date of Move</th>
                            <th class="px-3 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Player Added</th>
                            <th class="px-3 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Player Dropped</th>
                        </tr>
                    </thead>
                    <tbody class="bg-gray-800 divide-y divide-gray-700">
        `;

        sortedMoves.forEach(move => {
            logHtml += `
                <tr class="hover:bg-gray-700/50">
                    <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${move.date}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm text-green-400">${move.added_player.player_name}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm text-red-400">${move.dropped_player.player_name}</td>
                </tr>
            `;
        });

        logHtml += `
                    </tbody>
                </table>
            </div>
        `;
        simLogContainer.innerHTML = logHtml;
    }

    function handleSimulateClick() {
            const checkedBox = document.querySelector('input[name="player-to-add"]:checked');
            const droppedPlayerOption = playerDropDropdown.options[playerDropDropdown.selectedIndex];
            const transactionDate = transactionDatePicker.value;

            if (!checkedBox) {
                alert("Please check a player to add.");
                return;
            }
            if (!droppedPlayerOption.value) {
                alert("Please select a player to drop.");
                return;
            }
            if (!transactionDate) {
                alert("Please select a transaction date.");
                return;
            }

            if (droppedPlayerOption.dataset.type === 'simulated') {
                const addDate = droppedPlayerOption.dataset.addDate;
                if (transactionDate < addDate) {
                    alert(`Error: Cannot drop ${droppedPlayerOption.text.split('(')[0].trim()} on ${transactionDate} because they are not scheduled to be added until ${addDate}.`);
                    return;
                }
            }

            // Find Added Player
            const addedPlayerId = checkedBox.value;
            const tableType = checkedBox.dataset.table;
            const addedPlayer = (tableType === 'waivers' ? allWaiverPlayers : allFreeAgents).find(p => p.player_id == addedPlayerId);

            if (!addedPlayer) {
                console.error("Could not find added player object for ID:", addedPlayerId);
                alert("An error occurred trying to find the player to add. Please refresh and try again.");
                return;
            }

            // Find Dropped Player
            const droppedPlayerId = droppedPlayerOption.value;
            let droppedPlayer;
            if (droppedPlayerOption.dataset.type === 'roster') {
                droppedPlayer = currentTeamRoster.find(p => p.player_id == droppedPlayerId);
            } else {
                const sourceMove = simulatedMoves.find(m => m.added_player.player_id == droppedPlayerId);
                if (sourceMove) {
                    droppedPlayer = sourceMove.added_player;
                }
            }

            if (!droppedPlayer) {
                console.error("Could not find dropped player object for ID:", droppedPlayerId);
                alert("An error occurred trying to find the player to drop. Please refresh and try again.");
                return;
            }

            simulatedMoves.push({
                date: transactionDate,
                added_player: addedPlayer,
                dropped_player: droppedPlayer
            });

            localStorage.setItem(SIMULATION_KEY, JSON.stringify(simulatedMoves));

            // --- [START] FIX #2 ---
            // Re-fetch all data from the server to get new unused spots
            const selectedCategories = Array.from(document.querySelectorAll('#category-checkboxes-container input:checked')).map(cb => cb.value);
            fetchData(selectedCategories);
            // --- [END] FIX #2 ---

            // UI updates will be handled by fetchData, but we can still reset the form
            checkedBox.checked = false;
            // The dropdowns and log will be rebuilt by fetchData()
        }

    function handleResetClick() {
        if (confirm("Are you sure you want to reset all simulated moves?")) {
            simulatedMoves = [];
            localStorage.removeItem(SIMULATION_KEY);
            // We can just refresh the data to reset everything
            fetchData();
        }
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

    function setupEventListeners() {
        playerSearchInput.addEventListener('input', () => {
            filterAndSortPlayers();
            saveStateToCache();
        });
        recalculateButton.addEventListener('click', handleRecalculateClick);

        positionFiltersContainer.addEventListener('change', (e) => {
                    if (e.target.name === 'position-filter') {
                        filterAndSortPlayers(); // This now reads the checkboxes
                        saveStateToCache(); // Save the new state
                    }
                });

        dayFiltersContainer.addEventListener('change', (e) => {
                    if (e.target.name === 'day-filter') {
                        filterAndSortPlayers(); // This now reads the day checkboxes
                        saveStateToCache(); // Save the new state
                    }
                });

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
            currentUnusedSpots = cachedState.unusedRosterSpotsData;
            unusedRosterSpotsContainer.innerHTML = cachedState.unusedRosterSpotsHTML;

            // --- NEW: Load sim state from cache ---
            const cachedSim = localStorage.getItem(SIMULATION_KEY);
            simulatedMoves = cachedSim ? JSON.parse(cachedSim) : [];

            renderCategoryCheckboxes();
            renderPositionFilters();
            renderDayFilters();
            filterAndSortPlayers();
            populateDropPlayerDropdown();
            renderSimulatedMovesLog();
            populateTransactionDatePicker(currentWeekDates);
            setupEventListeners();
        } else {
            console.log("No valid cache. Fetching fresh data for Free Agents page.");
            // --- NEW: Load sim state even on fresh load ---
            const cachedSim = localStorage.getItem(SIMULATION_KEY);
            simulatedMoves = cachedSim ? JSON.parse(cachedSim) : [];
            setupEventListeners();
            fetchData();
            renderPositionFilters();
        }

        // --- NEW: Add listeners for sim buttons ---
        simulateButton.addEventListener('click', handleSimulateClick);
        resetButton.addEventListener('click', handleResetClick);
    }

    init();
})();
