/**
 * api.js
 * * This module is responsible for all communication with the backend server.
 * It abstracts away the fetch calls and error handling for a cleaner main application logic.
 */

// --- Configuration ---
const HOSTING_ENVIRONMENT = 'web'; // Or 'localhost' for testing
// Make sure this points to your live server URL
export const API_BASE_URL = HOSTING_ENVIRONMENT === 'localhost' ? 'http://127.0.0.1:5000' : 'https://www.fantasystreams.app';

// --- Private Helper Function ---
async function handleResponse(response) {
    if (response.status === 401) {
        // Handle unauthorized responses by reloading the page to trigger login.
        alert("Your session has expired. Please log in again.");
        window.location.reload();
        // Throw an error to stop the current promise chain
        throw new Error("Unauthorized");
    }
    if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.error || `HTTP error! status: ${response.status}`);
    }
     // Handle cases where response might be empty (e.g., logout)
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.indexOf("application/json") !== -1) {
        return response.json();
    }
    return {};
}

// --- Auth Functions ---
export async function checkAuthStatus() {
    const response = await fetch(`${API_BASE_URL}/api/auth/status`);
    // This specific call should not trigger a full page reload on 401
    if (!response.ok) {
        return { logged_in: false };
    }
    return response.json();
}

export async function checkLoginStatus() {
    try {
        // Add { cache: 'no-cache' } to the fetch request
        const response = await fetch(`${API_BASE_URL}/api/auth/status`, {
            cache: 'no-cache'
        });
        const data = await response.json();
        return data.logged_in;
    } catch (error) {
        console.error('Error checking login status:', error);
        return false;
    }
}

export async function logout() {
    await fetch(`${API_BASE_URL}/api/auth/logout`);
}

// --- Exported API Functions ---
export async function fetchLeagues() {
    const response = await fetch(`${API_BASE_URL}/api/leagues`);
    return handleResponse(response);
}

export async function fetchRosters(leagueId, week) {
    const params = new URLSearchParams({ league_id: leagueId });
    const response = await fetch(`${API_BASE_URL}/api/rosters/week/${week}?${params}`);
    return handleResponse(response);
}

export async function fetchMatchup(leagueId, week, team1, team2) {
    const params = new URLSearchParams({ league_id: leagueId, week, team1, team2 });
    const response = await fetch(`${API_BASE_URL}/api/matchup?${params}`);
    return handleResponse(response);
}

export async function fetchSimulatedData(leagueId, week, my_team, opponent, transactions) {
    const response = await fetch(`${API_BASE_URL}/api/simulate-week`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ league_id: leagueId, week, my_team, opponent, transactions })
    });
    return handleResponse(response);
}

export async function fetchWeeklyUtilization(leagueId, team, week) {
    const params = new URLSearchParams({ league_id: leagueId, team, week });
    const response = await fetch(`${API_BASE_URL}/api/weekly-optimizer?${params}`);
    return handleResponse(response);
}

export async function fetchOptimalRoster(leagueId, my_team, opponent, week, date) {
    const params = new URLSearchParams({ league_id: leagueId, my_team, opponent, week, date });
    const response = await fetch(`${API_BASE_URL}/api/optimizer?${params}`);
    return handleResponse(response);
}

export async function fetchFreeAgents(leagueId, my_team, opponent, week, start = 0) {
    const params = new URLSearchParams({ league_id: leagueId, my_team, opponent, week, start });
    const response = await fetch(`${API_BASE_URL}/api/free-agents?${params}`);
    return handleResponse(response);
}

export async function fetchGoalieScenarios(leagueId, team, week, starts) {
    const params = new URLSearchParams({ league_id: leagueId, team, week, starts });
    const response = await fetch(`${API_BASE_URL}/api/goalie-scenarios?${params}`);
    return handleResponse(response);
}
