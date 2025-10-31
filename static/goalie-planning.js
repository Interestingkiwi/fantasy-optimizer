(async function() {
    // A short delay to ensure the page elements are in the DOM
    await new Promise(resolve => setTimeout(resolve, 0));

    // --- Page Elements ---
    const errorDiv = document.getElementById('db-error-message');
    const controlsDiv = document.getElementById('goalie-controls');

    // Dropdowns
    const weekSelect = document.getElementById('week-select');
    const yourTeamSelect = document.getElementById('your-team-select');
    const opponentSelect = document.getElementById('opponent-select');

    // Containers
    const currentStatsContainer = document.getElementById('current-stats-container');
    const simulatedStatsContainer = document.getElementById('simulated-stats-container');
    const opponentStatsContainer = document.getElementById('opponent-stats-container');
    const individualStartsContainer = document.getElementById('individual-starts-container');

    // --- Global State ---
    let pageData = null;        // All teams, weeks, matchups
    let baseStarts = [];        // The original starts fetched from the server
    let simulatedStarts = [];   // The scenarios the user has checked
    let baseTotals = {};        // "Frozen" totals for Your Team
    let opponentTotals = {};    // "Frozen" totals for Opponent
    let yourTeamName = "";      // Your team's name
    let opponentTeamName = "";  // Opponent's name

    // --- Constants ---
    const SCENARIOS = [
        { name: "Shutout",       w: 1, ga: 0, sv: 30, sa: 30, toi: 60, sho: 1 },
        { name: "1GA",           w: 1, ga: 1, sv: 29, sa: 30, toi: 60, sho: 0 },
        { name: "2GA",           w: 1, ga: 2, sv: 28, sa: 30, toi: 60, sho: 0 },
        { name: "3GA",           w: 0, ga: 3, sv: 27, sa: 30, toi: 60, sho: 0 },
        { name: "4GA",           w: 0, ga: 4, sv: 26, sa: 30, toi: 60, sho: 0 },
        { name: "5GA",           w: 0, ga: 5, sv: 25, sa: 30, toi: 60, sho: 0 },
        { name: "6GA",           w: 0, ga: 6, sv: 24, sa: 30, toi: 60, sho: 0 },
        { name: "4/GA/Pulled",   w: 0, ga: 4, sv: 11, sa: 15, toi: 20, sho: 0 }
    ];

    // [NEW] Colors for highlighting
    const COLORS = {
        win: 'bg-green-800/50',
        loss: 'bg-red-800/50',
        tie: '' // No background for a tie
    };

    async function init() {
        try {
            // Add event listener for checkbox clicks
            individualStartsContainer.addEventListener('click', handleCheckboxClick);

            // Fetch page data (weeks, teams, matchups)
            await fetchPageData();

            // Populate dropdowns
            populateDropdowns();

            // Set up event listeners for dropdowns
            setupEventListeners();

            // Set initial opponent
            updateOpponentDropdown();

            // Initial data load for stats
            await fetchAndRenderStats();

            controlsDiv.classList.remove('hidden');

        } catch (error) {
            console.error('Initialization error:', error);
            errorDiv.textContent = error.message;
            errorDiv.classList.remove('hidden');
            controlsDiv.classList.add('hidden');
        }
    }

    /**
     * Fetches static page data like weeks, teams, and matchups.
     */
    async function fetchPageData() {
        const response = await fetch('/api/matchup_page_data');
        const data = await response.json();
        if (!response.ok || !data.db_exists) {
            throw new Error(data.error || 'Database has not been initialized.');
        }
        pageData = data;
    }

    /**
     * Populates the Week, Your Team, and Opponent dropdowns.
     */
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
        opponentSelect.innerHTML = teamOptions;

        // Restore team selection
        const savedTeam = localStorage.getItem('selectedTeam');
        if (savedTeam) {
            yourTeamSelect.value = savedTeam;
        }

        // Restore week selection
        if (!sessionStorage.getItem('fantasySessionStarted')) {
            const currentWeek = pageData.current_week;
            weekSelect.value = currentWeek;
            localStorage.setItem('selectedWeek', currentWeek);
            sessionStorage.setItem('fantasySessionStarted', 'true');
        } else {
            const savedWeek = localStorage.getItem('selectedWeek');
            weekSelect.value = savedWeek ? savedWeek : pageData.current_week;
        }
    }

    /**
     * Sets up change listeners for the dropdowns.
     */
    function setupEventListeners() {
        weekSelect.addEventListener('change', async () => {
            localStorage.setItem('selectedWeek', weekSelect.value);
            updateOpponentDropdown();
            await fetchAndRenderStats();
        });
        yourTeamSelect.addEventListener('change', async () => {
            localStorage.setItem('selectedTeam', yourTeamSelect.value);
            updateOpponentDropdown();
            await fetchAndRenderStats();
        });
        opponentSelect.addEventListener('change', async () => {
            await fetchAndRenderStats();
        });
    }

    /**
     * Automatically selects the opponent based on the matchup data.
     */
    function updateOpponentDropdown() {
        const selectedWeek = weekSelect.value;
        const yourTeamName = yourTeamSelect.value;

        const matchup = pageData.matchups.find(m =>
            m.week == selectedWeek && (m.team1 === yourTeamName || m.team2 === yourTeamName)
        );

        if (matchup) {
            const opponentName = matchup.team1 === yourTeamName ? matchup.team2 : matchup.team1;
            opponentSelect.value = opponentName;
        } else {
            const firstOtherTeam = pageData.teams.find(t => t.name !== yourTeamName);
            if (firstOtherTeam) {
                opponentSelect.value = firstOtherTeam.name;
            }
        }
    }

    /**
     * Fetches all goalie stats for both selected teams and initiates rendering.
     */
    async function fetchAndRenderStats() {
        yourTeamName = yourTeamSelect.value;
        opponentTeamName = opponentSelect.value;
        const selectedWeek = weekSelect.value;

        if (!selectedWeek || !yourTeamName || !opponentTeamName) {
            currentStatsContainer.innerHTML = '<p class="text-gray-400">Please make all selections.</p>';
            return;
        }

        // Set loading state
        currentStatsContainer.innerHTML = '<p class="text-gray-400">Loading...</p>';
        simulatedStatsContainer.innerHTML = '<p class="text-gray-400">Loading...</p>';
        opponentStatsContainer.innerHTML = '<p class="text-gray-400">Loading...</p>';
        individualStartsContainer.innerHTML = '';

        try {
            const response = await fetch('/api/goalie_planning_stats', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    week: selectedWeek,
                    your_team_name: yourTeamName,
                    opponent_team_name: opponentTeamName
                })
            });

            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Failed to fetch stats.');

            // Store the fetched "real" starts
            baseStarts = data.your_team_stats.individual_starts || [];

            // Calculate and store "frozen" totals
            baseTotals = calculateTotals(baseStarts);
            opponentTotals = calculateTotals(data.opponent_team_stats.individual_starts || []);

            // Clear any old simulations
            simulatedStarts = [];

            // Call the master render function
            renderAllTables();

        } catch (error) {
            console.error('Error fetching stats:', error);
            currentStatsContainer.innerHTML = `<p class="text-red-400">Error: ${error.message}</p>`;
            simulatedStatsContainer.innerHTML = '';
            opponentStatsContainer.innerHTML = '';
        }
    }

    /**
     * Master render function. Calculates all totals and re-renders all tables.
     */
    function renderAllTables() {
        // Combine base starts and simulated starts for calculations
        const allStarts = [...baseStarts, ...simulatedStarts];

        // Calculate aggregate stats from ALL starts (base + sim)
        const simulatedTotals = calculateTotals(allStarts);

        // Render the three top tables
        // Pass opponentTotals to the first two for comparison
        renderAggregateStatsTable(currentStatsContainer, `Current Stats (${yourTeamName})`, baseTotals, opponentTotals);
        renderAggregateStatsTable(simulatedStatsContainer, `Simulated Stats (${yourTeamName})`, simulatedTotals, opponentTotals, true);
        renderAggregateStatsTable(opponentStatsContainer, `Opponent Stats (${opponentTeamName})`, opponentTotals, null, false); // No comparison for opponent

        // Render the bottom "Individual Goalie Starts" table
        renderIndividualStartsTable(allStarts, simulatedTotals);
    }

    /**
     * Calculates aggregate stats from a list of start objects.
     */
    function calculateTotals(starts) {
        let totalW = 0, totalGA = 0, totalSV = 0, totalSA = 0, totalSHO = 0, totalTOI = 0;

        starts.forEach(start => {
            totalW += (start.W || start.w || 0); // 'W' from real, 'w' from sim
            totalGA += (start.GA || start.ga || 0);
            totalSV += (start.SV || start.sv || 0);
            totalSA += (start.SA || start.sa || 0);
            totalSHO += (start.SHO || start.sho || 0);
            // Real starts have 'TOI/G' (with SHO fix), sims have 'toi'
            totalTOI += (start['TOI/G'] || start.toi || 0);
        });

        const totalGAA = totalTOI > 0 ? (totalGA * 60) / totalTOI : 0;
        const totalSVpct = totalSA > 0 ? totalSV / totalSA : 0;

        return {
            starts: starts.length,
            W: totalW,
            GA: totalGA,
            SV: totalSV,
            SA: totalSA,
            SHO: totalSHO,
            TOI: totalTOI,
            GAA: totalGAA,
            SVpct: totalSVpct
        };
    }

    // --- [NEW] Helper function to get win/loss/tie class ---
    /**
     * Compares a stat value to an opponent's value and returns a color class.
     * @param {number} value - The team's stat value.
     * @param {number} opponentValue - The opponent's stat value.
     * @param {boolean} lowerIsBetter - True for stats like GAA.
     * @returns {string} - The CSS class from COLORS.
     */
    function getComparisonClass(value, opponentValue, lowerIsBetter = false) {
        if (lowerIsBetter) {
            // Handle GAA (and potential future stats)
            // Use a small epsilon for float comparison
            if (value < opponentValue - 1e-9) return COLORS.win;
            if (value > opponentValue + 1e-9) return COLORS.loss;
        } else {
            // Handle W, SV%, SHO
            if (value > opponentValue + 1e-9) return COLORS.win;
            if (value < opponentValue - 1e-9) return COLORS.loss;
        }
        return COLORS.tie; // Tie
    }

    /**
     * Generic renderer for the top aggregate stats tables.
     * [MODIFIED] Now accepts opponentTotals for comparison.
     */
    function renderAggregateStatsTable(container, title, totals, opponentTotals = null, isSimulated = false) {
        // Highlight simulated table
        const titleClass = isSimulated ? "text-blue-300" : "text-white";
        const shadowClass = isSimulated ? "shadow-blue-500/30 shadow-lg" : "shadow";

        // [NEW] Get color classes if opponentTotals is provided
        let wClass = COLORS.tie, gaaClass = COLORS.tie, svPctClass = COLORS.tie, shoClass = COLORS.tie;
        if (opponentTotals) {
            wClass = getComparisonClass(totals.W, opponentTotals.W, false);
            // For GAA, use Infinity if TOI is 0 to ensure it "loses" if opponent has 0.00 GAA
            const myGaa = totals.TOI > 0 ? totals.GAA : Infinity;
            const oppGaa = opponentTotals.TOI > 0 ? opponentTotals.GAA : Infinity;
            // Handle 0/0 tie
            if (myGaa === Infinity && oppGaa === Infinity) {
                gaaClass = COLORS.tie;
            } else {
                gaaClass = getComparisonClass(myGaa, oppGaa, true);
            }

            svPctClass = getComparisonClass(totals.SVpct, opponentTotals.SVpct, false);
            shoClass = getComparisonClass(totals.SHO, opponentTotals.SHO, false);
        }

        let tableHtml = `
            <div class="bg-gray-900 rounded-lg ${shadowClass}">
                <h3 class="text-lg font-bold ${titleClass} p-3 bg-gray-800 rounded-t-lg">
                    ${title}
                </h3>
                <table class="w-full divide-y divide-gray-700">
                    <thead class="bg-gray-700/50">
                        <tr>
                            <th class="px-3 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">Stat</th>
                            <th class="px-3 py-2 text-right text-xs font-bold text-gray-300 uppercase tracking-wider">Value</th>
                        </tr>
                    </thead>
                    <tbody class="bg-gray-800 divide-y divide-gray-700">
                        <tr class="hover:bg-gray-700/50">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">Goalie Starts</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300 text-right font-bold">${totals.starts}</td>
                        </tr>
                        <tr class="hover:bg-gray-700/50 ${wClass}">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">Wins (W)</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-right">${totals.W.toFixed(0)}</td>
                        </tr>
                        <tr class="hover:bg-gray-700/50 ${gaaClass}">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">Goals Against Avg (GAA)</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-right">${(totals.TOI > 0 ? totals.GAA : 0).toFixed(3)}</td>
                        </tr>
                        <tr class="hover:bg-gray-700/50">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-normal text-gray-400 pl-6">Goals Against (GA)</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-400 text-right">${totals.GA.toFixed(0)}</td>
                        </tr>
                        <tr class="hover:bg-gray-700/50">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-normal text-gray-400 pl-6">Time on Ice (TOI)</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-400 text-right">${totals.TOI.toFixed(1)}</td>
                        </tr>
                        <tr class="hover:bg-gray-700/50 ${svPctClass}">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">Save Pct (SV%)</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-right">${totals.SVpct.toFixed(3)}</td>
                        </tr>
                        <tr class="hover:bg-gray-700/50">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-normal text-gray-400 pl-6">Saves (SV)</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-400 text-right">${totals.SV.toFixed(0)}</td>
                        </tr>
                        <tr class="hover:bg-gray-700/50">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-normal text-gray-400 pl-6">Shots Against (SA)</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-400 text-right">${totals.SA.toFixed(0)}</td>
                        </tr>
                        <tr class="hover:bg-gray-700/50 ${shoClass}">
                            <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">Shutouts (SHO)</td>
                            <td class="px-3 py-2 whitespace-nowrap text-sm text-right">${totals.SHO.toFixed(0)}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        `;
        container.innerHTML = tableHtml;
    }

    /**
     * Renders the individual starts table, including sims, totals, and scenarios.
     */
    function renderIndividualStartsTable(allStarts, totals) {
        const headers = ['Start #', 'Date', 'Player', 'W', 'GA', 'SV', 'SA', 'SV%', 'GAA', 'SHO'];

        let tableHtml = `
            <div class="bg-gray-900 rounded-lg shadow">
                <h3 class="text-lg font-bold text-white p-3 bg-gray-800 rounded-t-lg">
                    Individual Goalie Starts
                </h3>
                <div class="overflow-x-auto">
                    <table class="w-full divide-y divide-gray-700">
                        <thead class="bg-gray-700/50">
                            <tr>
                                ${headers.map(h => `<th class="px-3 py-2 text-left text-xs font-bold text-gray-300 uppercase tracking-wider">${h}</th>`).join('')}
                            </tr>
                        </thead>
                        <tbody class="bg-gray-800 divide-y divide-gray-700">
        `;

        // --- 1. Render Base (Real) Starts ---
        baseStarts.forEach((start, index) => {
            tableHtml += `<tr class="hover:bg-gray-700/50">
                <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">${index + 1}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${start.date}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">${start.player_name}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(start.W || 0).toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(start.GA || 0).toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(start.SV || 0).toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(start.SA || 0).toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(start['SV%'] || 0).toFixed(3)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(start.GAA || 0).toFixed(3)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(start.SHO || 0).toFixed(0)}</td>
            </tr>`;
        });

        // --- 2. Render Simulated Starts ---
        simulatedStarts.forEach((sim, index) => {
            const simGAA = sim.toi > 0 ? (sim.ga * 60) / sim.toi : 0;
            const simSVpct = sim.sa > 0 ? sim.sv / sim.sa : 0;

            tableHtml += `<tr class="hover:bg-gray-700/50 bg-blue-900/30">
                <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">${baseStarts.length + index + 1}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">
                    <label class="flex items-center">
                        <input type="checkbox" class="sim-checkbox form-checkbox bg-gray-800 border-gray-600 rounded" data-sim-index="${index}" checked />
                        <span class="ml-2">Remove</span>
                    </label>
                </td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-medium text-gray-300">${sim.name}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(sim.w || 0).toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(sim.ga || 0).toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(sim.sv || 0).toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(sim.sa || 0).toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${simSVpct.toFixed(3)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${simGAA.toFixed(3)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm text-gray-300">${(sim.sho || 0).toFixed(0)}</td>
            </tr>`;
        });

        // --- 3. Render the Total Row ---
        tableHtml += `
            <tr class="bg-gray-700/50 border-t-2 border-gray-500">
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">${totals.starts}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white"></td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">TOTALS</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">${totals.W.toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">${totals.GA.toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">${totals.SV.toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">${totals.SA.toFixed(0)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">${(totals.TOI > 0 ? totals.SVpct : 0).toFixed(3)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">${(totals.TOI > 0 ? totals.GAA : 0).toFixed(3)}</td>
                <td class="px-3 py-2 whitespace-nowrap text-sm font-bold text-white">${totals.SHO.toFixed(0)}</td>
            </tr>
        `;

        // --- 4. Render New Scenarios ---
        const nextStartNum = allStarts.length + 1;

        SCENARIOS.forEach(scenario => {
            // Calculate new cumulative stats by adding scenario delta to totals
            const newW = totals.W + scenario.w;
            const newGA = totals.GA + scenario.ga;
            const newSV = totals.SV + scenario.sv;
            const newSA = totals.SA + scenario.sa;
            const newSHO = totals.SHO + scenario.sho;
            const newTOI = totals.TOI + scenario.toi;

            const newGAA = newTOI > 0 ? (newGA * 60) / newTOI : 0;
            const newSVpct = newSA > 0 ? newSV / newSA : 0;

            tableHtml += `
                <tr class="hover:bg-gray-700/50 text-gray-400 italic">
                    <td class="px-3 py-2 whitespace-nowrap text-sm">${nextStartNum}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm">
                        <label class="flex items-center">
                            <input type="checkbox" class="scenario-checkbox form-checkbox bg-gray-800 border-gray-600 rounded" data-scenario-name="${scenario.name}" />
                            <span class="ml-2">Use</span>
                        </label>
                    </td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm font-medium">${scenario.name}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm">${newW.toFixed(0)}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm">${newGA.toFixed(0)}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm">${newSV.toFixed(0)}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm">${newSA.toFixed(0)}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm">${newSVpct.toFixed(3)}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm">${newGAA.toFixed(3)}</td>
                    <td class="px-3 py-2 whitespace-nowrap text-sm">${newSHO.toFixed(0)}</td>
                </tr>
            `;
        });

        tableHtml += `
                        </tbody>
                    </table>
                </div>
            </div>
        `;
        individualStartsContainer.innerHTML = tableHtml;
    }

    /**
     * Handles checkbox clicks on the individual starts table.
     */
    function handleCheckboxClick(e) {
        const target = e.target;

        // --- Handle ADDING a scenario ---
        if (target.classList.contains('scenario-checkbox') && target.checked) {
            const scenarioName = target.dataset.scenarioName;
            const scenarioToAdd = SCENARIOS.find(s => s.name === scenarioName);
            if (scenarioToAdd) {
                simulatedStarts.push(scenarioToAdd);
                renderAllTables();
            }
        }

        // --- Handle REMOVING a scenario ---
        if (target.classList.contains('sim-checkbox') && !target.checked) {
            const simIndex = parseInt(target.dataset.simIndex, 10);
            if (!isNaN(simIndex) && simIndex >= 0 && simIndex < simulatedStarts.length) {
                simulatedStarts.splice(simIndex, 1);
                renderAllTables();
            }
        }
    }

    init();
})();
