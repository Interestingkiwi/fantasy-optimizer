/**
 * api.js
 * * This module is responsible for all communication with the backend server.
 * It abstracts away the fetch calls and error handling for a cleaner main application logic.
 */

// --- Configuration ---
const HOSTING_ENVIRONMENT = 'web'; // Toggle between 'localhost' and 'web'
const API_BASE_URL = HOSTING_ENVIRONMENT === 'localhost' ? 'http://127.0.0.1:5000' : '';

// --- Private Helper Function ---
async function handleResponse(response) {
    if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.error || `HTTP error! status: ${response.status}`);
    }
    return response.json();
}

// --- Exported API Functions ---
export async function fetchRosters(week) {
    const response = await fetch(`${API_BASE_URL}/api/rosters/week/${week}`);
    return handleResponse(response);
}

export async function fetchMatchup(week, team1, team2) {
    const params = new URLSearchParams({ week, team1, team2 });
    const response = await fetch(`${API_BASE_URL}/api/matchup?${params}`);
    return handleResponse(response);
}

export async function fetchSimulatedData(week, my_team, opponent, transactions) {
    const response = await fetch(`${API_BASE_URL}/api/simulate-week`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ week, my_team, opponent, transactions })
    });
    return handleResponse(response);
}

export async function fetchWeeklyUtilization(team, week) {
    const params = new URLSearchParams({ team, week });
    const response = await fetch(`${API_BASE_URL}/api/weekly-optimizer?${params}`);
    return handleResponse(response);
}

export async function fetchOptimalRoster(my_team, opponent, week, date) {
    const params = new URLSearchParams({ my_team, opponent, week, date });
    const response = await fetch(`${API_BASE_URL}/api/optimizer?${params}`);
    return handleResponse(response);
}

export async function fetchFreeAgents(my_team, opponent, week, start = 0) {
    const params = new URLSearchParams({ my_team, opponent, week, start });
    const response = await fetch(`${API_BASE_URL}/api/free-agents?${params}`);
    return handleResponse(response);
}

export async function fetchGoalieScenarios(team, week, starts) {
    const params = new URLSearchParams({ team, week, starts });
    const response = await fetch(`${API_BASE_URL}/api/goalie-scenarios?${params}`);
    return handleResponse(response);
}
