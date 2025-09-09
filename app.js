document.addEventListener('DOMContentLoaded', () => {
    // --- Element References ---
    const myTeamSelector = document.getElementById('myTeamSelector');
    const opponentSelector = document.getElementById('opponentSelector');
    const weekSelector = document.getElementById('weekSelector');
    const runAnalysisBtn = document.getElementById('runAnalysisBtn');
    const dateSelector = document.getElementById('dateSelector');
    const optimizeBtn = document.getElementById('optimizeBtn');
    const loadRawDataBtn = document.getElementById('loadRawDataBtn');
    const transactionSimulatorContainer = document.getElementById('transactionSimulatorContainer');
    const simulateBtn = document.getElementById('simulateBtn');
    const goalieStartsSelector = document.getElementById('goalieStartsSelector');
    const goalieScenarioBtn = document.getElementById('goalieScenarioBtn');
    const rostersContainer = document.getElementById('rostersContainer');
    const matchupContainer = document.getElementById('matchupContainer');
    const optimizerContainer = document.getElementById('optimizerContainer');
    const utilizationContainer = document.getElementById('utilizationContainer');
    const freeAgentContainer = document.getElementById('freeAgentContainer');
    const goalieContainer = document.getElementById('goalieContainer');

    // --- State ---
    let freeAgentStartIndex = 0;
    let currentRosterData = {};
    let allFreeAgents = [];

    // --- Configuration ---
    const STATS_TO_DISPLAY_H2H = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk', 'w', 'so', 'svpct', 'ga'];
    const FANTASY_WEEKS = 25;
    const MAX_TRANSACTIONS = 4;

    // --- Initial Setup ---
    populateWeekSelector();
    createTransactionRows();
    runAnalysisBtn.addEventListener('click', runFullWeeklyAnalysis);
    optimizeBtn.addEventListener('click', fetchAndDisplayOptimalRoster);
    loadRawDataBtn.addEventListener('click', fetchAndDisplayAllRosters);
    simulateBtn.addEventListener('click', fetchAndDisplaySimulatedData);
    goalieScenarioBtn.addEventListener('click', fetchAndDisplayGoalieScenarios);

    dateSelector.value = new Date().toISOString().split('T')[0];
    fetchAndPopulateSelectors();

    // --- Main Functions ---

    async function fetchAndPopulateSelectors() {
        const selectedWeek = weekSelector.value;
        try {
            const response = await fetch(`http://127.0.0.1:5000/api/rosters/week/${selectedWeek}`);
            currentRosterData = await handleResponse(response);
            populateTeamSelectors(currentRosterData);
        } catch (error) {
            console.error("Failed to populate team selectors on initial load:", error);
            alert("Could not load initial team data. Please ensure the backend server is running.");
        }
    }

    async function runFullWeeklyAnalysis() {
        clearAllSections();
        await Promise.all([
            fetchAndDisplayMatchup(),
            fetchAndDisplayWeeklyUtilization(),
            fetchAndDisplayFreeAgents(0)
        ]);
        populateTransactionSimulator();
    }

    async function fetchAndDisplayMatchup() {
        const myTeam = myTeamSelector.value;
        const opponent = opponentSelector.value;
        const week = weekSelector.value;
        if (myTeam === opponent) { alert("Please select two different teams."); return; }

        showLoading(matchupContainer, `Loading matchup...`);
        try {
            const response = await fetch(`http://127.0.0.1:5000/api/matchup?week=${week}&team1=${myTeam}&team2=${opponent}`);
            const data = await handleResponse(response);
            matchupContainer.innerHTML = '';
            matchupContainer.appendChild(createSummaryTable(myTeam, data[myTeam].full_week_proj, data[myTeam].live_proj, opponent, data[opponent].full_week_proj, data[opponent].live_proj));
            if (data.off_days) {
                matchupContainer.appendChild(createOffDaysSection(data.off_days));
            }
        } catch (error) {
            showError(matchupContainer, error.message);
        }
    }

    async function fetchAndDisplaySimulatedData() {
        const myTeam = myTeamSelector.value;
        const opponent = opponentSelector.value;
        const week = weekSelector.value;

        const transactions = [];
        for (let i = 0; i < MAX_TRANSACTIONS; i++) {
            const addPlayer = document.getElementById(`add-player-${i}`).value;
            const dropPlayer = document.getElementById(`drop-player-${i}`).value;
            const transDate = document.getElementById(`trans-date-${i}`).value;
            if (addPlayer && dropPlayer && transDate) {
                transactions.push({ add: addPlayer, drop: dropPlayer, date: transDate });
            }
        }

        if (transactions.length === 0) {
            alert("Please define at least one transaction to simulate.");
            return;
        }

        showLoading(matchupContainer, `Simulating week with ${transactions.length} move(s)...`);
        showLoading(utilizationContainer, ''); // Also show loading indicator here

        try {
            const response = await fetch(`http://127.0.0.1:5000/api/simulate-week`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ week, my_team: myTeam, opponent, transactions })
            });
            const data = await handleResponse(response);

            // Update Matchup Table
            matchupContainer.innerHTML = '';
            matchupContainer.appendChild(createSummaryTable(myTeam, null, data.simulated_matchup[myTeam].totals, opponent, null, data.simulated_matchup[opponent].totals, "Simulated Matchup Results"));

            // Update Utilization Table
            utilizationContainer.innerHTML = '';
            utilizationContainer.appendChild(createUtilizationTable(data.simulated_utilization, `Simulated Roster Utilization`));

        } catch (error) {
            showError(matchupContainer, error.message);
            showError(utilizationContainer, "Simulation failed.");
        }
    }

    async function fetchAndDisplayWeeklyUtilization() {
        const myTeam = myTeamSelector.value;
        const week = weekSelector.value;
        showLoading(utilizationContainer, `Analyzing utilization...`);
        try {
            const response = await fetch(`http://127.0.0.1:5000/api/weekly-optimizer?team=${myTeam}&week=${week}`);
            const data = await handleResponse(response);
            utilizationContainer.innerHTML = '';
            utilizationContainer.appendChild(createUtilizationTable(data.roster_utilization, `Roster Utilization`));
            if (data.open_slots) {
                utilizationContainer.appendChild(createOpenSlotsTable(data.open_slots));
            }
        } catch (error) {
            showError(utilizationContainer, error.message);
        }
    }

    async function fetchAndDisplayOptimalRoster() {
        // ... (this function remains the same)
        const myTeam = myTeamSelector.value;
        const opponent = opponentSelector.value;
        const week = weekSelector.value;
        const date = dateSelector.value;
        if (myTeam === opponent) { alert("Your team and opponent must be different."); return; }

        showLoading(optimizerContainer, `Finding optimal lineup for ${date}...`);

        try {
            const response = await fetch(`http://127.0.0.1:5000/api/optimizer?my_team=${myTeam}&opponent=${opponent}&week=${week}&date=${date}`);
            const data = await handleResponse(response);
            optimizerContainer.innerHTML = '';

            const title = document.createElement('h3');
            title.textContent = `Optimal Lineup for ${date}`;
            const closeBtn = document.createElement('button');
            closeBtn.textContent = 'Close';
            closeBtn.className = 'close-btn';
            closeBtn.onclick = () => optimizerContainer.innerHTML = '';
            title.appendChild(closeBtn);
            optimizerContainer.appendChild(title);

            const container = document.createElement('div');
            container.className = 'optimizer-container';
            container.appendChild(createOptimizerSection('Starting Lineup', data.optimal_roster));
            container.appendChild(createOptimizerContextSection('Optimization Context', data.context));
            optimizerContainer.appendChild(container);

            const benchTitle = document.createElement('h3');
            benchTitle.textContent = `Bench for ${date}`;
            optimizerContainer.appendChild(benchTitle);
            optimizerContainer.appendChild(createOptimizerSection('', data.benched_players, false));
        } catch (error) {
            showError(optimizerContainer, error.message);
        }
    }

    async function fetchAndDisplayFreeAgents(startIndex = 0) {
        // ... (this function remains the same)
        freeAgentStartIndex = startIndex;
        const myTeam = myTeamSelector.value;
        const opponent = opponentSelector.value;
        const week = weekSelector.value;
        if (myTeam === opponent) { return; }

        showLoading(freeAgentContainer, 'Searching for top free agents...');

        try {
            const response = await fetch(`http://127.0.0.1:5000/api/free-agents?my_team=${myTeam}&opponent=${opponent}&week=${week}&start=${startIndex}`);
            const data = await handleResponse(response);
            allFreeAgents = data.free_agents; // Store for simulator

            freeAgentContainer.innerHTML = '';
            const title = document.createElement('h3');
            title.textContent = `Top Free Agent Suggestions for Week ${week}`;
            freeAgentContainer.appendChild(title);
            freeAgentContainer.appendChild(createFreeAgentTable(data.free_agents, data.context.category_weights));
            freeAgentContainer.appendChild(createFreeAgentPagination(startIndex, data.free_agents.length));
        } catch (error) {
            showError(freeAgentContainer, error.message);
        }
    }

    async function fetchAndDisplayGoalieScenarios() {
        const myTeam = myTeamSelector.value;
        const week = weekSelector.value;
        const starts = goalieStartsSelector.value;

        showLoading(goalieContainer, `Calculating scenarios for ${starts} future start(s)...`);
        try {
            const response = await fetch(`http://127.0.0.1:5000/api/goalie-scenarios?team=${myTeam}&week=${week}&starts=${starts}`);
            const data = await handleResponse(response);
            goalieContainer.innerHTML = '';
            goalieContainer.appendChild(createGoalieScenariosTable(data));
        } catch (error) {
            showError(goalieContainer, error.message);
        }
    }

    async function fetchAndDisplayAllRosters() {
        // ... (this function remains the same)
        const selectedWeek = weekSelector.value;
        showLoading(rostersContainer, `Loading raw roster data for week ${selectedWeek}...`);
        clearAllSections(rostersContainer);
         try {
            const response = await fetch(`http://127.0.0.1:5000/api/rosters/week/${selectedWeek}`);
            const allRosters = await handleResponse(response);
            rostersContainer.innerHTML = '';
            for (const teamName in allRosters) {
                const teamTitle = document.createElement('h2');
                teamTitle.textContent = teamName;
                rostersContainer.appendChild(teamTitle);
                rostersContainer.appendChild(createPlayerTable(allRosters[teamName], 'g'));
            }
        } catch (error) {
            showError(rostersContainer, error.message);
        }
    }

    // --- UI Creation Helper Functions ---

    function populateWeekSelector() { for (let i = 1; i <= FANTASY_WEEKS; i++) weekSelector.add(new Option(`Week ${i}`, i)); }

    function populateTeamSelectors(rosters) {
        const teamNames = Object.keys(rosters);
        [myTeamSelector, opponentSelector].forEach(sel => {
            sel.innerHTML = '';
            teamNames.forEach(name => sel.add(new Option(name, name)));
        });
        if (teamNames.length > 1) opponentSelector.value = teamNames[1];
    }

    function createSummaryTable(team1, totals1Full, totals1Live, team2, totals2Full, totals2Live, titleText = "Current Projected Matchup") {
        const container = document.createElement('div');
        const title = document.createElement('h3');
        title.textContent = titleText;
        container.appendChild(title);

        const table = document.createElement('table');
        table.className = 'totals-table';
        table.innerHTML = `
            <thead>
                <tr>
                    <th>Category</th>
                    <th>${team1} (Full)</th>
                    <th>${team1} (Live)</th>
                    <th>${team2} (Full)</th>
                    <th>${team2} (Live)</th>
                </tr>
            </thead>`;
        const tbody = document.createElement('tbody');
        const inverseStats = ['ga'];

        STATS_TO_DISPLAY_H2H.forEach(stat => {
            const t1_full = totals1Full ? (totals1Full[stat] !== undefined ? totals1Full[stat] : 0) : 'N/A';
            const t1_live = totals1Live ? (totals1Live[stat] !== undefined ? totals1Live[stat] : 0) : 'N/A';
            const t2_full = totals2Full ? (totals2Full[stat] !== undefined ? totals2Full[stat] : 0) : 'N/A';
            const t2_live = totals2Live ? (totals2Live[stat] !== undefined ? totals2Live[stat] : 0) : 'N/A';

            const isInverse = inverseStats.includes(stat);
            let full1_style = '', full2_style = '', live1_style = '', live2_style = '';

            if (t1_full !== 'N/A' && t2_full !== 'N/A') {
                if ((!isInverse && t1_full > t2_full) || (isInverse && t1_full < t2_full)) {
                    full1_style = 'background-color: #d4edda;'; // Green for team 1 win
                    full2_style = 'background-color: #f8d7da;'; // Red for team 2 loss
                } else if ((!isInverse && t2_full > t1_full) || (isInverse && t2_full < t1_full)) {
                    full2_style = 'background-color: #d4edda;'; // Green for team 2 win
                    full1_style = 'background-color: #f8d7da;'; // Red for team 1 loss
                }
            }
            if (t1_live !== 'N/A' && t2_live !== 'N/A') {
                if ((!isInverse && t1_live > t2_live) || (isInverse && t1_live < t2_live)) {
                    live1_style = 'background-color: #d4edda;';
                    live2_style = 'background-color: #f8d7da;';
                } else if ((!isInverse && t2_live > t1_live) || (isInverse && t2_live < t1_live)) {
                    live2_style = 'background-color: #d4edda;';
                    live1_style = 'background-color: #f8d7da;';
                }
            }

            tbody.innerHTML += `
                <tr>
                    <td>${stat.toUpperCase()}</td>
                    <td style="${full1_style}">${t1_full}</td>
                    <td style="${live1_style}">${t1_live}</td>
                    <td style="${full2_style}">${t2_full}</td>
                    <td style="${live2_style}">${t2_live}</td>
                </tr>`;
        });
        table.appendChild(tbody);
        container.appendChild(table);
        return container;
    }

    function createOffDaysSection(offDays) {
        const container = document.createElement('div');
        const title = document.createElement('h4');
        title.style.marginTop = '1em';
        title.textContent = 'League Off-Days This Week';
        container.appendChild(title);

        if (offDays.length > 0) {
            const list = document.createElement('p');
            list.style.fontSize = '0.9em';
            list.textContent = offDays.map(d => new Date(d + 'T00:00:00').toLocaleDateString(undefined, { weekday: 'short', month: 'numeric', day: 'numeric' })).join(', ');
            container.appendChild(list);
        } else {
            container.innerHTML += '<p>No league-wide off-days this week.</p>';
        }
        return container;
    }

    function createUtilizationTable(roster, titleText) {
        // ... (this function remains the same)
        const container = document.createElement('div');
        const title = document.createElement('h3');
        title.textContent = titleText;
        container.appendChild(title);

        const table = document.createElement('table');
        table.innerHTML = `<thead><tr><th>Player</th><th>Positions</th><th>Games</th><th>Starts</th><th>Util %</th><th>Start Days</th></tr></thead>`;
        const tbody = document.createElement('tbody');
        roster.sort((a,b) => b.starts_this_week - a.starts_this_week);
        roster.forEach(player => {
            const games = player.games_this_week, starts = player.starts_this_week;
            const util = games > 0 ? `${((starts / games) * 100).toFixed(0)}%` : 'N/A';
            const row = document.createElement('tr');
            row.innerHTML = `<td>${player.name}</td><td>${player.positions}</td><td>${games}</td><td>${starts}</td><td>${util}</td><td>${player.start_days || ''}</td>`;
            if (games > 0 && starts < games) row.style.backgroundColor = '#fff5f5';
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        container.appendChild(table);
        return container;
    }

    function createOpenSlotsTable(slotsByDay) {
        const container = document.createElement('div');
        const title = document.createElement('h3');
        title.style.marginTop = '1em';
        title.textContent = 'Open Roster Slots';
        container.appendChild(title);

        const table = document.createElement('table');
        const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        const positions = ['C', 'LW', 'RW', 'D', 'G'];

        let headerHtml = '<thead><tr><th>Day</th>';
        positions.forEach(p => headerHtml += `<th>${p}</th>`);
        headerHtml += '</tr></thead>';
        table.innerHTML = headerHtml;

        const tbody = document.createElement('tbody');
        days.forEach(day => {
            const slots = slotsByDay[day];
            if (slots) {
                let rowHtml = `<td>${day}</td>`;
                positions.forEach(p => {
                    const count = slots[p] || 0;
                    const style = count > 0 ? 'style="background-color: #d4edda;"' : '';
                    rowHtml += `<td ${style}>${count}</td>`;
                });
                tbody.innerHTML += `<tr>${rowHtml}</tr>`;
            }
        });
        table.appendChild(tbody);
        container.appendChild(table);
        return container;
    }

    function createGoalieScenariosTable(data) {
        const container = document.createElement('div');
        const title = document.createElement('h3');
        title.textContent = 'Goalie Stat Scenarios';
        container.appendChild(title);

        const table = document.createElement('table');
        table.innerHTML = `
            <thead>
                <tr>
                    <th>Scenario</th>
                    <th>Resulting GAA</th>
                    <th>Resulting SV%</th>
                </tr>
            </thead>`;
        const tbody = document.createElement('tbody');

        const currentStatsRow = `
            <tr style="font-weight: bold;">
                <td>Current Stats</td>
                <td>${data.current_gaa.toFixed(3)}</td>
                <td>${data.current_svpct.toFixed(3)}</td>
            </tr>
        `;
        tbody.innerHTML += currentStatsRow;

        data.scenarios.forEach(s => {
            tbody.innerHTML += `
                <tr>
                    <td>${s.name}</td>
                    <td>${s.gaa.toFixed(3)}</td>
                    <td>${s.svpct.toFixed(3)}</td>
                </tr>
            `;
        });
        table.appendChild(tbody);
        container.appendChild(table);
        return container;
    }

    function createOptimizerSection(title, players, isStarting = true) {
        // ... (this function remains the same)
        const div = document.createElement('div');
        div.className = 'team-section';
        if (title) {
            const h4 = document.createElement('h4');
            h4.textContent = title;
            div.appendChild(h4);
        }
        div.appendChild(createOptimizerTable(players, isStarting));
        return div;
    }

    function createOptimizerTable(players, isStarting) {
        // ... (this function remains the same)
        const table = document.createElement('table');
        const header = isStarting ? '<th>Player</th><th>Pos</th><th>Team</th><th>Value</th>' : '<th>Player</th><th>Pos</th><th>Team</th><th>Proj. Pts</th>';
        table.innerHTML = `<thead><tr>${header}</tr></thead>`;
        const tbody = document.createElement('tbody');
        if (players.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4">No players</td></tr>`;
        } else {
            players.forEach(p => {
                const value = isStarting ? (p.marginal_value || 0).toFixed(2) : ((p.per_game_projections && p.per_game_projections.pts) || '0');
                tbody.innerHTML += `<tr><td>${p.name}</td><td>${p.positions}</td><td>${p.team}</td><td>${value}</td></tr>`;
            });
        }
        table.appendChild(tbody);
        return table;
    }

    function createOptimizerContextSection(title, context) {
        // ... (this function remains the same)
        const div = document.createElement('div');
        div.className = 'team-section';
        const h4 = document.createElement('h4');
        h4.textContent = title;
        div.appendChild(h4);

        const table = document.createElement('table');
        table.className = 'context-table';
        table.innerHTML = '<thead><tr><th>Category</th><th>Weight</th><th>My Proj.</th><th>Opp Proj.</th></tr></thead>';
        const tbody = document.createElement('tbody');
        for(const stat in context.category_weights) {
            tbody.innerHTML += `
                <tr>
                    <td>${stat.toUpperCase()}</td>
                    <td>${context.category_weights[stat].toFixed(2)}</td>
                    <td>${context.my_team_totals[stat] || 0}</td>
                    <td>${context.opponent_totals[stat] || 0}</td>
                </tr>
            `;
        }
        table.appendChild(tbody);
        div.appendChild(table);
        return div;
    }

    function createFreeAgentTable(freeAgents, weights) {
        const table = document.createElement('table');
        const headerStats = STATS_TO_DISPLAY_H2H.map(stat => {
            const weight = weights[stat] || 0;
            const style = weight >= 2.0 ? 'style="background-color: #ffeeba;"' : '';
            return `<th ${style}>${stat.toUpperCase()}</th>`;
        }).join('');
        table.innerHTML = `<thead><tr><th>Player</th><th>Positions</th><th>Games</th>${headerStats}<th>Start Days</th><th>Drop Candidate</th></tr></thead>`;

        const tbody = document.createElement('tbody');
        if (freeAgents.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${5 + STATS_TO_DISPLAY_H2H.length}">No valuable free agents found.</td></tr>`;
        } else {
            freeAgents.forEach(fa => {
                const statCells = STATS_TO_DISPLAY_H2H.map(stat => `<td>${fa.weekly_projections[stat] || 0}</td>`).join('');
                tbody.innerHTML += `
                    <tr>
                        <td>${fa.name}</td>
                        <td>${fa.positions}</td>
                        <td>${fa.games_this_week}</td>
                        ${statCells}
                        <td>${fa.start_days}</td>
                        <td>${fa.suggested_drop}</td>
                    </tr>`;
            });
        }
        table.appendChild(tbody);
        return table;
    }

    function createFreeAgentPagination(startIndex, resultCount) {
        // ... (this function remains the same)
        const div = document.createElement('div');
        div.className = 'pagination-controls';
        const prevBtn = document.createElement('button');
        prevBtn.textContent = '<< Previous';
        prevBtn.disabled = startIndex === 0;
        prevBtn.addEventListener('click', () => fetchAndDisplayFreeAgents(startIndex - 20));

        const nextBtn = document.createElement('button');
        nextBtn.textContent = 'Next >>';
        nextBtn.disabled = resultCount < 20;
        nextBtn.addEventListener('click', () => fetchAndDisplayFreeAgents(startIndex + 20));

        div.appendChild(prevBtn);
        div.appendChild(nextBtn);
        return div;
    }

    function createPlayerTable(rosterData, statToDisplay) {
        // ... (this function remains the same)
        const table = document.createElement('table');
        const statHeader = statToDisplay.toUpperCase();
        table.innerHTML = `<thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>Games</th><th>Proj. ${statHeader}</th></tr></thead>`;
        const tbody = document.createElement('tbody');
        rosterData.forEach(player => {
            let weeklyStat = 'N/A';
            if (player.weekly_projections && player.weekly_projections[statToDisplay] !== undefined) {
                weeklyStat = player.weekly_projections[statToDisplay];
            }
            tbody.innerHTML += `<tr><td>${player.name}</td><td>${player.positions}</td><td>${player.team}</td><td>${player.games_this_week}</td><td>${weeklyStat}</td></tr>`;
        });
        table.appendChild(tbody);
        return table;
    }

    function createTransactionRows() {
        for(let i=0; i < MAX_TRANSACTIONS; i++) {
            const row = document.createElement('div');
            row.className = 'transaction-row';
            row.innerHTML = `
                <label>Add:</label> <select id="add-player-${i}"><option value="">-- Select Player --</option></select>
                <label>Drop:</label> <select id="drop-player-${i}"><option value="">-- Select Player --</option></select>
                <label>Date:</label> <input type="date" id="trans-date-${i}">
            `;
            transactionSimulatorContainer.appendChild(row);
        }
    }

    function populateTransactionSimulator() {
        const myTeam = myTeamSelector.value;
        const myRoster = currentRosterData[myTeam] || [];

        for(let i=0; i < MAX_TRANSACTIONS; i++) {
            const addSelect = document.getElementById(`add-player-${i}`);
            const dropSelect = document.getElementById(`drop-player-${i}`);

            // Re-populate dynamically
            addSelect.innerHTML = '<option value="">-- Select FA --</option>';
            allFreeAgents.forEach(fa => addSelect.add(new Option(fa.name, fa.name)));

            dropSelect.innerHTML = '<option value="">-- Select Player --</option>';
            myRoster.forEach(p => dropSelect.add(new Option(p.name, p.name)));

            // Add change listener to update subsequent dropdowns
            addSelect.onchange = () => updateDynamicRoster();
            dropSelect.onchange = () => updateDynamicRoster();
        }
        updateDynamicRoster(); // Initial population
    }

    function updateDynamicRoster() {
        const myTeam = myTeamSelector.value;
        let simulatedRoster = [...(currentRosterData[myTeam] || [])];

        for (let i = 0; i < MAX_TRANSACTIONS; i++) {
            const addPlayerName = document.getElementById(`add-player-${i}`).value;
            const dropPlayerName = document.getElementById(`drop-player-${i}`).value;

            // Simulate the drop for subsequent rows
            if (dropPlayerName) {
                simulatedRoster = simulatedRoster.filter(p => p.name !== dropPlayerName);
            }
            // Simulate the add for subsequent rows
            if (addPlayerName) {
                const fa = allFreeAgents.find(p => p.name === addPlayerName);
                if (fa) simulatedRoster.push(fa);
            }

            // Update the *next* drop-down list
            if (i + 1 < MAX_TRANSACTIONS) {
                const nextDropSelect = document.getElementById(`drop-player-${i+1}`);
                const currentSelection = nextDropSelect.value;
                nextDropSelect.innerHTML = '<option value="">-- Select Player --</option>';
                simulatedRoster.forEach(p => nextDropSelect.add(new Option(p.name, p.name)));
                nextDropSelect.value = currentSelection; // Preserve selection if possible
            }
        }
    }


    // --- Generic Helper Functions ---
    function showLoading(container, message) {
        container.innerHTML = `<p>${message}</p>`;
    }

    function showError(container, message) {
        container.innerHTML = `<p style="color: red;">Error: ${message}</p>`;
    }

    function clearAllSections(except = null) {
        [rostersContainer, matchupContainer, optimizerContainer, utilizationContainer, freeAgentContainer, goalieContainer].forEach(container => {
            if (container !== except) container.innerHTML = '';
        });
    }

    async function handleResponse(response) {
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || `HTTP error! status: ${response.status}`);
        }
        return response.json();
    }

    // --- Initial Load ---
    populateWeekSelector();
    fetchAndPopulateSelectors();
});
