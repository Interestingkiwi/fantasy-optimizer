(async function() {
    // A short delay to ensure the page elements are in the DOM
    await new Promise(resolve => setTimeout(resolve, 0));

    const errorDiv = document.getElementById('db-error-message');
    const controlsDiv = document.getElementById('lineup-controls');
    const tableContainer = document.getElementById('roster-table-container');
    const optimalLineupContainer = document.getElementById('optimal-lineup-container');
    const unusedRosterSpotsContainer = document.getElementById('unused-roster-spots-container');
    const weekSelect = document.getElementById('week-select');
    const checkboxesContainer = document.getElementById('category-checkboxes-container');
    const yourTeamSelect = document.getElementById('your-team-select');

    let pageData = null; // To store weeks and teams
    const CATEGORY_PREF_KEY = 'lineupCategoryPreferences';
    let allScoringCategories = []; // Store all categories
    let checkedCategories = []; // Store currently checked categories

    /**
     * Calculates a color for a heat map based on a player's rank.
     * Lower ranks (closer to 1) are green, higher ranks (closer to 20) are red.
     * @param {number} rank The player's rank in a category.
     * @returns {string} An HSL color string or an empty string if rank is invalid.
     */
    function getHeatmapColor(rank) {
        if (rank === null || rank === undefined || rank === '-') {
            return ''; // No color for empty ranks
        }

        const minRank = 1;
        const maxRank = 20;

        // Clamp the rank to be within our min/max range for color calculation
        const clampedRank = Math.max(minRank, Math.min(rank, maxRank));

        // Calculate the percentage of where the rank falls between min and max.
        // A rank of 1 will be 0%, a rank of 20 will be 100%.
        const percentage = (clampedRank - minRank) / (maxRank - minRank);

        // We want green (hue 120) at 0% and red (hue 0) at 100%.
        // So, we calculate the hue by scaling (1 - percentage) over the 120-degree hue range.
        const hue = (1 - percentage) * 120;

        // Return a very pastel HSL color. Low saturation and high lightness create a soft effect.
        return `hsl(${hue}, 65%, 75%)`;
    }

    async function init() {
        try {
            const response = await fetch('/api/lineup_page_data');
            const data = await response.json();

            if (!response.ok || !data.db_exists) {
                throw new Error(data.error || 'Database has not been initialized.');
            }

            pageData = data;
            populateDropdowns();
            const savedCategories = localStorage.getItem(CATEGORY_PREF_KEY);
            if (savedCategories) {
                checkedCategories = JSON.parse(savedCategories);
            }
            setupEventListeners();

            // Initial data load
            await fetchAndRenderTable();

            controlsDiv.classList.remove('hidden');

        } catch (error) {
            console.error('Initialization error:', error);
            errorDiv.classList.remove('hidden');
            controlsDiv.classList.add('hidden');
            tableContainer.classList.add('hidden');
            optimalLineupContainer.classList.add('hidden');
        }
    }

    function populateDropdowns() {
        // Populate Weeks
        weekSelect.innerHTML = pageData.weeks.map(week =>
            `<option value="${week.week_num}">
                Week ${week.week_num} (${week.start_date} to ${week.end_date})
            </option>`
        ).join('');

        // Populate Teams
        const teamOptions = pageData.teams.map(team =>
            `<option value="${team.name}">${team.name}</option>`
        ).join('');
        yourTeamSelect.innerHTML = teamOptions;

        // --- EDITED SECTION ---
        // Restore team selection from localStorage
        const savedTeam = localStorage.getItem('selectedTeam');
        if (savedTeam) {
            yourTeamSelect.value = savedTeam;
        }

        // Check if a session has started to handle the week selection
        if (!sessionStorage.getItem('fantasySessionStarted')) {
            // This is a new session. Default to the current week.
            const currentWeek = pageData.current_week;
            weekSelect.value = currentWeek;
            localStorage.setItem('selectedWeek', currentWeek);
            sessionStorage.setItem('fantasySessionStarted', 'true');
        } else {
            // A session is active. Restore from localStorage.
            const savedWeek = localStorage.getItem('selectedWeek');
            if (savedWeek) {
                weekSelect.value = savedWeek;
            } else {
                weekSelect.value = pageData.current_week;
            }
        }
        // --- END EDITED SECTION ---
    }

    async function fetchAndRenderTable() {
        const selectedWeek = weekSelect.value;
        const yourTeamName = yourTeamSelect.value;

        if (!selectedWeek || !yourTeamName) {
            tableContainer.innerHTML = '<p class="text-gray-400">Please make all selections.</p>';
            return;
        }

        tableContainer.innerHTML = '<p class="text-gray-400">Loading roster...</p>';
        optimalLineupContainer.innerHTML = '<p class="text-gray-400">Calculating optimal lineups...</p>';
        unusedRosterSpotsContainer.innerHTML = '';

            // Read checked categories from the UI, if it's rendered
            const categoryCheckboxes = document.querySelectorAll('#category-checkboxes-container input[name="category"]:checked');
            let categoriesToSend = null;

            if (categoryCheckboxes.length > 0) {
                categoriesToSend = Array.from(categoryCheckboxes).map(cb => cb.value);
            } else if (checkedCategories.length > 0) {
                categoriesToSend = checkedCategories;
            }

        try {
            const response = await fetch('/api/roster_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    week: selectedWeek,
                    team_name: yourTeamName,
                    categories: categoriesToSend
                })
            });

            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Failed to fetch roster.');

            if (allScoringCategories.length === 0) {
                allScoringCategories = data.scoring_categories;
                if (localStorage.getItem(CATEGORY_PREF_KEY) === null) {
                  checkedCategories = data.checked_categories;
                }
                renderCategoryCheckboxes(); // New function
            }


            renderTable(data.players, data.scoring_categories, data.daily_optimal_lineups);
            renderOptimalLineups(data.daily_optimal_lineups, data.lineup_settings);
            renderUnusedRosterSpotsTable(data.unused_roster_spots);


        } catch(error) {
            console.error('Error fetching roster:', error);
            tableContainer.innerHTML = `<p class="text-red-400">Error: ${error.message}</p>`;
            optimalLineupContainer.innerHTML = '<p class="text-red-400">Could not generate lineups.</p>';
        }
    }

    function renderTable(roster, scoringCategories, dailyLineups) {
        const positionOrder = ['C', 'LW', 'RW', 'D', 'G', 'IR', 'IR+'];

        // Create a lookup map for which days each player starts
        const playerStartsByDay = {};
        const dayAbbrMap = {
            'Monday': 'Mon', 'Tuesday': 'Tue', 'Wednesday': 'Wed',
            'Thursday': 'Thu', 'Friday': 'Fri', 'Saturday': 'Sat', 'Sunday': 'Sun'
        };

        for (const dayString in dailyLineups) {
            const lineup = dailyLineups[dayString];
            const dayName = dayString.split(',')[0]; // e.g., "Monday"
            const dayAbbr = dayAbbrMap[dayName];   // e.g., "Mon"

            if (dayAbbr) {
                for (const position in lineup) {
                    lineup[position].forEach(player => {
                        if (!playerStartsByDay[player.player_name]) {
                            playerStartsByDay[player.player_name] = new Set();
                        }
                        playerStartsByDay[player.player_name].add(dayAbbr);
                    });
                }
            }
        }

        roster.sort((a, b) => {
            const posA = a.eligible_positions.split(',').map(p => p.trim());
            const posB = b.eligible_positions.split(',').map(p => p.trim());

            const maxIndexA = Math.max(...posA.map(p => positionOrder.indexOf(p)));
            const maxIndexB = Math.max(...posB.map(p => positionOrder.indexOf(p)));

            return maxIndexA - maxIndexB;
        });

        let tableHtml = `
            <div class="bg-gray-900 rounded-lg shadow">
                <h2 class="text-xl font-bold text-white p-3 bg-gray-800 rounded-t-lg">Roster</h2>
                <table class="min-w-full divide-y divide-gray-700">
                    <thead class="bg-gray-700/50">
                        <tr>
                            <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Player Name</th>
                            <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Team</th>
                            <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Positions</th>
                            <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">This Week</th>
                            <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider"># Games</th>
                            <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Starts</th>
                            <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Next Week</th>
        `;

        (scoringCategories || []).forEach(cat => {
            tableHtml += `<th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">${cat}</th>`;
        });

        tableHtml += `
                        </tr>
                    </thead>
                    <tbody class="bg-gray-800 divide-y divide-gray-700">
        `;

        roster.forEach(player => {
            // Create the highlighted games list based on optimal starts
            const gamesThisWeekHtml = player.games_this_week.map(day => {
                if (playerStartsByDay[player.player_name] && playerStartsByDay[player.player_name].has(day)) {
                    return `<strong class="text-yellow-300">${day}</strong>`;
                }
                return day;
            }).join(', ');

            tableHtml += `
                <tr class="hover:bg-gray-700/50">
                    <td class="px-2 py-1 whitespace-nowrap text-sm font-medium text-gray-300">${player.player_name}</td>
                    <td class="px-2 py-1 whitespace-nowrap text-sm text-gray-300">${player.team}</td>
                    <td class="px-2 py-1 whitespace-nowrap text-sm text-gray-300">${player.eligible_positions}</td>
                    <td class="px-2 py-1 whitespace-nowrap text-sm text-gray-300">${gamesThisWeekHtml}</td>
                    <td class="px-2 py-1 whitespace-nowrap text-sm text-gray-300">${player.games_this_week.length}</td>
                    <td class="px-2 py-1 whitespace-nowrap text-sm text-gray-300">${player.starts_this_week}</td>
                    <td class="px-2 py-1 whitespace-nowrap text-sm text-gray-300">${(player.games_next_week || []).join(', ')}</td>
            `;
            (scoringCategories || []).forEach(cat => {
                const rank_key = cat + '_cat_rank';
                let rank = '-';

                if (player.hasOwnProperty(rank_key) && player[rank_key] !== null) {
                    rank = player[rank_key];
                }

                const color = getHeatmapColor(rank);
                // For pastel colors, a darker text provides better contrast
                tableHtml += `<td class="px-2 py-1 whitespace-nowrap text-sm text-center font-semibold text-gray-600" style="background-color: ${color};">${rank}</td>`;
            });


            tableHtml += `
                </tr>
            `;
        });

        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;
        tableContainer.innerHTML = tableHtml;
    }

    function renderOptimalLineups(dailyLineups, lineupSettings) {
        let finalHtml = '<div class="flex flex-wrap gap-4 justify-center">'; // Flex container
        const positionOrder = ['C', 'LW', 'RW', 'D', 'G'];

        // Get the day keys and sort them chronologically
        const sortedDays = Object.keys(dailyLineups).sort((a, b) => {
            // Append a year to make parsing reliable, since the date strings don't have one
            const currentYear = new Date().getFullYear();
            const dateA = new Date(`${a}, ${currentYear}`);
            const dateB = new Date(`${b}, ${currentYear}`);
            return dateA - dateB;
        });

        // Iterate over the sorted array of days
        sortedDays.forEach(day => {
            const lineup = dailyLineups[day];

            // Each table container will be a flex item
            let tableHtml = `
                <div class="bg-gray-900 rounded-lg shadow flex-grow" style="min-width: 300px;">
                    <h2 class="text-xl font-bold text-white p-3 bg-gray-800 rounded-t-lg">${day}</h2>
                    <table class="w-full divide-y divide-gray-700">
                        <thead class="bg-gray-700/50">
                            <tr>
                                <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Position</th>
                                <th scope="col" class="px-2 py-1 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Player Name</th>
                            </tr>
                        </thead>
                        <tbody class="bg-gray-800 divide-y divide-gray-700">
            `;

            positionOrder.forEach(pos => {
                const numSlots = lineupSettings[pos] || 0;
                const playersInPos = lineup[pos] || [];

                for (let i = 0; i < numSlots; i++) {
                    const player = playersInPos[i];
                    if (player) {
                         tableHtml += `
                            <tr class="hover:bg-gray-700/50">
                                <td class="px-2 py-1 whitespace-nowrap text-sm font-medium text-gray-300">${pos}</td>
                                <td class="px-2 py-1 whitespace-nowrap text-sm text-gray-300">${player.player_name}</td>
                            </tr>
                        `;
                    } else {
                        // Render an empty slot
                        tableHtml += `
                            <tr class="hover:bg-gray-700/50">
                                <td class="px-2 py-1 whitespace-nowrap text-sm font-medium text-gray-300">${pos}</td>
                                <td class="px-2 py-1 whitespace-nowrap text-sm text-gray-500 italic">(Empty)</td>
                            </tr>
                        `;
                    }
                }
            });

            tableHtml += `
                        </tbody>
                    </table>
                </div>
            `;
            finalHtml += tableHtml;
        });

        if (sortedDays.length === 0) {
            optimalLineupContainer.innerHTML = '<p class="text-gray-400">No games scheduled for active players this week.</p>';
        } else {
            finalHtml += '</div>'; // Close the flex container
            optimalLineupContainer.innerHTML = finalHtml;
        }
    }

    function renderUnusedRosterSpotsTable(unusedSpotsData) {
        if (!unusedSpotsData) {
            unusedRosterSpotsContainer.innerHTML = '';
            return;
        }

        const positionOrder = ['C', 'LW', 'RW', 'D', 'G'];
        const dayOrder = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

        const sortedDays = Object.keys(unusedSpotsData).sort((a, b) => {
            return dayOrder.indexOf(a) - dayOrder.indexOf(b);
        });

        let tableHtml = `
            <div class="bg-gray-900 rounded-lg shadow mt-6">
                <h2 class="text-xl font-bold text-white p-3 bg-gray-800 rounded-t-lg">Unused Roster Spots</h2>
                <table class="divide-y divide-gray-700">
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

        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;

        unusedRosterSpotsContainer.innerHTML = tableHtml;
    }


    function renderCategoryCheckboxes() {
        let checkboxHtml = `
            <div class="flex justify-between items-center mb-2">
                <label class="block text-sm font-medium text-gray-300">Update Lineup Priority Based On:</label>
                <div>
                    <button id="check-all-btn" class="text-xs bg-gray-600 hover:bg-gray-500 text-white py-1 px-2 rounded mr-2 transition-colors duration-150">Check All</button>
                    <button id="uncheck-all-btn" class="text-xs bg-gray-600 hover:bg-gray-500 text-white py-1 px-2 rounded transition-colors duration-150">Uncheck All</button>
                </div>
            </div>
            <div class="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 mb-4">
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

        // Add the Update button
        checkboxHtml += `
            <button id="update-lineups-btn" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2 px-4 rounded transition-colors duration-150">
                Update Lineups
            </button>
        `;
        checkboxesContainer.innerHTML = checkboxHtml;

        // Add event listeners for new buttons
        document.getElementById('check-all-btn').addEventListener('click', () => {
            document.querySelectorAll('#category-checkboxes-container input[name="category"]').forEach(cb => cb.checked = true);
        });

        document.getElementById('uncheck-all-btn').addEventListener('click', () => {
            document.querySelectorAll('#category-checkboxes-container input[name="category"]').forEach(cb => cb.checked = false);
        });

        // The "Update Lineups" button will trigger the fetch
        document.getElementById('update-lineups-btn').addEventListener('click', () => {
            const currentChecked = Array.from(
                document.querySelectorAll('#category-checkboxes-container input[name="category"]:checked')
            ).map(cb => cb.value);

            localStorage.setItem(CATEGORY_PREF_KEY, JSON.stringify(currentChecked));

            fetchAndRenderTable();
        });
    }




    function setupEventListeners() {
        weekSelect.addEventListener('change', fetchAndRenderTable);
        yourTeamSelect.addEventListener('change', fetchAndRenderTable);
    }

    init();
})();
