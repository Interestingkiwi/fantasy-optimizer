/**
 * main.js
 *
 * This is the main entry point for the frontend application.
 * It imports functionality from the api.js and ui.js modules,
 * manages the application state, and orchestrates the different parts
 * by setting up event listeners and handling user interactions.
 */

import * as api from './api.js';
import * as ui from './ui.js';
import { API_BASE_URL } from './api.js'; // <-- Import the base URL

document.addEventListener('DOMContentLoaded', () => {

    // --- Element References ---
    const loginBtn = document.getElementById('loginBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const rememberMeCheckbox = document.getElementById('rememberMeCheckbox');
    const leagueSelector = document.getElementById('leagueSelector');
    const leagueIdInput = document.getElementById('leagueIdInput');
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
    const allContainers = [rostersContainer, matchupContainer, optimizerContainer, utilizationContainer, freeAgentContainer, goalieContainer];

    // --- State ---
    let freeAgentStartIndex = 0;
    let currentRosterData = {};
    let allFreeAgents = [];

    // --- Helper Functions ---
    function getSelectedLeagueId() {
        return leagueIdInput.value.trim() || leagueSelector.value;
    }

    // --- Event Handlers ---

    async function handleInitialLoad() {
        // Before checking auth status, try to auto-login which might be triggered
        // by the backend if a token is cached.
        if (window.location.pathname === '/') { // Only on the main page
            const authStatus = await api.checkAuthStatus();
            if (authStatus.logged_in) {
                ui.showMainView();
                initializeMainView();
            } else {
                 // Try to login automatically if there might be a cache
                window.location.href = '/api/auth/login?remember=true';
            }
        }
    }

    async function initializeMainView() {
        ui.populateWeekSelector(weekSelector);
        ui.createTransactionRows(transactionSimulatorContainer);
        dateSelector.value = new Date().toISOString().split('T')[0];

        try {
            const leagues = await api.fetchLeagues();
            if (leagues.error) throw new Error(leagues.error);
            ui.populateLeagueSelector(leagueSelector, leagues);
            if (getSelectedLeagueId()) {
                await handleLeagueChange();
            }
        } catch (error) {
            console.error("Failed to load leagues:", error);
            alert(`Could not load your Yahoo leagues: ${error.message}. You can still enter a League ID manually.`);
        }
    }


    async function handleLeagueChange() {
        const leagueId = getSelectedLeagueId();
        const week = weekSelector.value;
        if (!leagueId) return;

        ui.showLoading(myTeamSelector, 'Loading...');
        ui.showLoading(opponentSelector, 'Loading...');
        ui.clearAllSections(allContainers);

        try {
            currentRosterData = await api.fetchRosters(leagueId, week);
            if (Object.keys(currentRosterData).length === 0 || currentRosterData.error) {
                 throw new Error(currentRosterData.error || "No teams found in this league.");
            }
            ui.populateTeamSelectors(myTeamSelector, opponentSelector, currentRosterData);
        } catch (error) {
            console.error("Failed to populate team selectors:", error);
            alert(`Could not load team data for league ${leagueId}. Please check the ID and try again. Error: ${error.message}`);
            ui.populateTeamSelectors(myTeamSelector, opponentSelector, {}); // Clear selectors
        }
    }

    async function handleRunAnalysis() {
        const leagueId = getSelectedLeagueId();
        if (!leagueId) { alert("Please select or enter a league ID first."); return; }
        ui.clearAllSections(allContainers);
        await Promise.all([
            handleFetchMatchup(),
            handleFetchUtilization(),
            handleFetchFreeAgents(0)
        ]);
        populateTransactionSimulator();
    }

    async function handleFetchMatchup() {
        const leagueId = getSelectedLeagueId();
        const myTeam = myTeamSelector.value;
        const opponent = opponentSelector.value;
        const week = weekSelector.value;
        if (!leagueId || !myTeam || !opponent) { alert("Please select a league and both teams."); return; }
        if (myTeam === opponent) { alert("Please select two different teams."); return; }

        ui.showLoading(matchupContainer, `Loading matchup...`);
        try {
            const data = await api.fetchMatchup(leagueId, week, myTeam, opponent);
            matchupContainer.innerHTML = '';
            matchupContainer.appendChild(ui.createSummaryTable(myTeam, data[myTeam].full_week_proj, data[myTeam].live_proj, opponent, data[opponent].full_week_proj, data[opponent].live_proj));
            if (data.off_days) {
                matchupContainer.appendChild(ui.createOffDaysSection(data.off_days));
            }
        } catch (error) {
            ui.showError(matchupContainer, error.message);
        }
    }

    async function handleFetchSimulatedData() {
        const leagueId = getSelectedLeagueId();
        const myTeam = myTeamSelector.value;
        const opponent = opponentSelector.value;
        const week = weekSelector.value;
        if (!leagueId || !myTeam || !opponent) { alert("Please select a league and both teams."); return; }
        const transactions = [];

        for (let i = 0; i < 4; i++) {
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

        ui.showLoading(matchupContainer, `Simulating week...`);
        ui.showLoading(utilizationContainer, '');

        try {
            const data = await api.fetchSimulatedData(leagueId, week, myTeam, opponent, transactions);

            matchupContainer.innerHTML = '';
            matchupContainer.appendChild(ui.createSummaryTable(myTeam, null, data.simulated_matchup[myTeam].totals, opponent, null, data.simulated_matchup[opponent].totals, "Simulated Matchup Results"));

            utilizationContainer.innerHTML = '';
            utilizationContainer.appendChild(ui.createUtilizationTable(data.simulated_utilization, `Simulated Roster Utilization`));
        } catch (error) {
            ui.showError(matchupContainer, error.message);
            ui.showError(utilizationContainer, "Simulation failed.");
        }
    }

    async function handleFetchUtilization() {
        const leagueId = getSelectedLeagueId();
        const myTeam = myTeamSelector.value;
        const week = weekSelector.value;
        if (!leagueId || !myTeam) { alert("Please select a league and your team."); return; }
        ui.showLoading(utilizationContainer, `Analyzing utilization...`);
        try {
            const data = await api.fetchWeeklyUtilization(leagueId, myTeam, week);
            utilizationContainer.innerHTML = '';
            utilizationContainer.appendChild(ui.createUtilizationTable(data.roster_utilization, `Roster Utilization`));
            if (data.open_slots) {
                utilizationContainer.appendChild(ui.createOpenSlotsTable(data.open_slots));
            }
        } catch (error) {
            ui.showError(utilizationContainer, error.message);
        }
    }

    async function handleFetchOptimalRoster() {
        const leagueId = getSelectedLeagueId();
        const myTeam = myTeamSelector.value;
        const opponent = opponentSelector.value;
        const week = weekSelector.value;
        const date = dateSelector.value;
        if (!leagueId || !myTeam || !opponent) { alert("Please select a league and both teams."); return; }
        if (myTeam === opponent) { alert("Your team and opponent must be different."); return; }

        ui.showLoading(optimizerContainer, `Finding optimal lineup for ${date}...`);
        try {
            const data = await api.fetchOptimalRoster(leagueId, myTeam, opponent, week, date);
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
            container.appendChild(ui.createOptimizerSection('Starting Lineup', data.optimal_roster));
            container.appendChild(ui.createOptimizerContextSection('Optimization Context', data.context));
            optimizerContainer.appendChild(container);

            const benchTitle = document.createElement('h3');
            benchTitle.textContent = `Bench for ${date}`;
            optimizerContainer.appendChild(benchTitle);
            optimizerContainer.appendChild(ui.createOptimizerSection('', data.benched_players, false));
        } catch (error) {
            ui.showError(optimizerContainer, error.message);
        }
    }

    async function handleFetchFreeAgents(startIndex) {
        freeAgentStartIndex = startIndex;
        const leagueId = getSelectedLeagueId();
        const myTeam = myTeamSelector.value;
        const opponent = opponentSelector.value;
        const week = weekSelector.value;
        if (!leagueId || !myTeam || !opponent) { return; }

        ui.showLoading(freeAgentContainer, 'Searching for top free agents...');
        try {
            const data = await api.fetchFreeAgents(leagueId, myTeam, opponent, week, startIndex);
            allFreeAgents = data.free_agents;

            freeAgentContainer.innerHTML = '';
            const title = document.createElement('h3');
            title.textContent = `Top Free Agent Suggestions for Week ${week}`;
            freeAgentContainer.appendChild(title);
            freeAgentContainer.appendChild(ui.createFreeAgentTable(data.free_agents, data.context.category_weights));
            freeAgentContainer.appendChild(ui.createFreeAgentPagination(startIndex, data.free_agents.length, handleFetchFreeAgents));
        } catch (error) {
            ui.showError(freeAgentContainer, error.message);
        }
    }

    async function handleFetchGoalieScenarios() {
        const leagueId = getSelectedLeagueId();
        const myTeam = myTeamSelector.value;
        const week = weekSelector.value;
        const starts = goalieStartsSelector.value;
        if (!leagueId || !myTeam) { alert("Please select a league and your team."); return; }

        ui.showLoading(goalieContainer, `Calculating scenarios for ${starts} future start(s)...`);
        try {
            const data = await api.fetchGoalieScenarios(leagueId, myTeam, week, starts);
            goalieContainer.innerHTML = '';
            goalieContainer.appendChild(ui.createGoalieScenariosTable(data));
        } catch (error) {
            ui.showError(goalieContainer, error.message);
        }
    }

    async function handleFetchAllRosters() {
        const leagueId = getSelectedLeagueId();
        const selectedWeek = weekSelector.value;
        if (!leagueId) { alert("Please select or enter a league ID first."); return; }

        ui.showLoading(rostersContainer, `Loading raw roster data for week ${selectedWeek}...`);
        ui.clearAllSections([matchupContainer, optimizerContainer, utilizationContainer, freeAgentContainer, goalieContainer]);
        try {
            const allRosters = await api.fetchRosters(leagueId, selectedWeek);
            currentRosterData = allRosters; // Update state
            ui.populateTeamSelectors(myTeamSelector, opponentSelector, currentRosterData);

            rostersContainer.innerHTML = '';
            for (const teamName in allRosters) {
                const teamTitle = document.createElement('h2');
                teamTitle.textContent = teamName;
                rostersContainer.appendChild(teamTitle);
                rostersContainer.appendChild(ui.createPlayerTable(allRosters[teamName], 'g'));
            }
        } catch (error) {
            ui.showError(rostersContainer, error.message);
        }
    }

    // --- Transaction Simulator Logic ---
    function populateTransactionSimulator() {
        const myTeam = myTeamSelector.value;
        const myRoster = currentRosterData[myTeam] || [];

        for(let i=0; i < 4; i++) {
            const addSelect = document.getElementById(`add-player-${i}`);
            const dropSelect = document.getElementById(`drop-player-${i}`);

            addSelect.innerHTML = '<option value="">-- Select FA --</option>';
            allFreeAgents.forEach(fa => addSelect.add(new Option(fa.name, fa.name)));

            dropSelect.innerHTML = '<option value="">-- Select Player --</option>';
            myRoster.forEach(p => dropSelect.add(new Option(p.name, p.name)));

            addSelect.onchange = updateDynamicRoster;
            dropSelect.onchange = updateDynamicRoster;
        }
        updateDynamicRoster();
    }

    function updateDynamicRoster() {
        const myTeam = myTeamSelector.value;
        let simulatedRoster = [...(currentRosterData[myTeam] || [])];

        for (let i = 0; i < 4; i++) {
            const addPlayerName = document.getElementById(`add-player-${i}`).value;
            const dropPlayerName = document.getElementById(`drop-player-${i}`).value;

            if (dropPlayerName) {
                simulatedRoster = simulatedRoster.filter(p => p.name !== dropPlayerName);
            }
            if (addPlayerName) {
                const fa = allFreeAgents.find(p => p.name === addPlayerName);
                if (fa) simulatedRoster.push(fa);
            }

            if (i + 1 < 4) {
                const nextDropSelect = document.getElementById(`drop-player-${i+1}`);
                const currentSelection = nextDropSelect.value;
                nextDropSelect.innerHTML = '<option value="">-- Select Player --</option>';
                simulatedRoster.forEach(p => nextDropSelect.add(new Option(p.name, p.name)));
                nextDropSelect.value = currentSelection;
            }
        }
    }

    // --- Initial Setup & Event Listeners ---

    // This function now just updates the href on the login anchor tag
    function updateLoginLink() {
        const rememberMe = rememberMeCheckbox.checked;
        loginBtn.href = `${API_BASE_URL}/api/auth/login?remember=${rememberMe}`;
    }

    rememberMeCheckbox.addEventListener('change', updateLoginLink);
    updateLoginLink(); // Set initial href

    logoutBtn.addEventListener('click', async () => {
        try {
            await api.logout();
            window.location.reload();
        } catch (error) {
            console.error("Logout failed:", error);
            window.location.reload(); // Still reload even if logout fails
        }
    });

    // This handles the case where the user is already logged in (via session or cache)
    api.checkAuthStatus().then(authStatus => {
        if (authStatus.logged_in) {
            ui.showMainView();
            initializeMainView();
        } else {
            ui.showLoginView();
        }
    });


    leagueSelector.addEventListener('change', handleLeagueChange);
    leagueIdInput.addEventListener('change', handleLeagueChange);
    weekSelector.addEventListener('change', handleLeagueChange);

    runAnalysisBtn.addEventListener('click', handleRunAnalysis);
    optimizeBtn.addEventListener('click', handleFetchOptimalRoster);
    loadRawDataBtn.addEventListener('click', handleFetchAllRosters);
    simulateBtn.addEventListener('click', handleFetchSimulatedData);
    goalieScenarioBtn.addEventListener('click', handleFetchGoalieScenarios);

});
