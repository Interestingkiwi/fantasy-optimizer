/**
 * players.js
 *
 * This script handles the functionality for the new "All Available Players" page.
 * It fetches the current team roster and all available free agents/waiver players,
 * then renders them in two separate tables. The available players table includes
 * comprehensive sorting functionality.
 */

import { API_BASE_URL } from './api.js';

document.addEventListener('DOMContentLoaded', () => {
    // --- Element References ---
    const pageTitle = document.getElementById('pageTitle');
    const rosterContainer = document.getElementById('rosterContainer');
    const availablePlayersContainer = document.getElementById('availablePlayersContainer');

    // --- State ---
    let allAvailablePlayersData = []; // To store data for sorting
    let currentSort = { key: 'cat_coverage_rank', direction: 'asc' }; // Default sort

    // --- Initial Setup ---
    const params = new URLSearchParams(window.location.search);
    const leagueId = params.get('league_id'); // Still useful for context, but not for API call
    const teamName = params.get('team_name');
    const week = params.get('week');

    if (!leagueId || !teamName || !week) {
        pageTitle.textContent = "Error: Missing league, team, or week information in URL.";
        return;
    }

    pageTitle.textContent = `Player Overview for ${decodeURIComponent(teamName)} (Week ${week})`;

    /**
     * Generates an HSL color string for a heatmap based on a player's category rank.
     * @param {number} rank - The player's rank in a category (1-20).
     * @returns {string} An inline style string with a background color.
     */
    function getRankColor(rank) {
        if (rank === null || rank === undefined || rank < 1 || rank > 20) {
            return ''; // No color for invalid ranks
        }
        // Hue goes from 120 (green) for rank 1 down to 0 (red) for rank 20.
        const hue = 120 - ((rank - 1) * (120 / 19));
        return `style="background-color: hsl(${hue}, 70%, 85%); color: #333;"`;
    }

    /**
     * Creates a player table element.
     * @param {Array} players - Array of player objects.
     * @param {string} tableId - A unique ID for the table element.
     * @param {boolean} isSortable - If true, headers will be marked as sortable.
     * @returns {HTMLTableElement} The created table element.
     */
    function createPlayerTable(players, tableId, isSortable = false) {
        const table = document.createElement('table');
        table.id = tableId;
        const STATS_TO_DISPLAY = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk', 'w', 'so', 'svpct', 'gaa'];

        const headerStats = STATS_TO_DISPLAY.map(stat =>
            `<th ${isSortable ? `class="sortable" data-sort-key="${stat}"` : ''}>${stat.toUpperCase()}</th>`
        ).join('');

        const sortableClass = isSortable ? 'class="sortable"' : '';

        table.innerHTML = `
            <thead>
                <tr>
                    <th ${sortableClass} data-sort-key="name">Player</th>
                    <th ${sortableClass} data-sort-key="team">Team</th>
                    <th ${sortableClass} data-sort-key="availability">Status</th>
                    <th ${sortableClass} data-sort-key="positions">Positions</th>
                    <th ${sortableClass} data-sort-key="games_this_week">Games</th>
                    <th ${sortableClass} data-sort-key="cat_coverage_rank">Cat Coverage Rank</th>
                    ${headerStats}
                </tr>
            </thead>
            <tbody>
            </tbody>`;

        populateTableBody(table, players);
        return table;
    }

    /**
     * Populates the body of a player table with player data.
     * @param {HTMLTableElement} table - The table to populate.
     * @param {Array} players - The player data to render.
     */
    function populateTableBody(table, players) {
        const tbody = table.querySelector('tbody');
        tbody.innerHTML = '';
        const STATS_TO_DISPLAY = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk', 'w', 'so', 'svpct', 'gaa'];
        const STATS_FOR_HEATMAP = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk'];


        if (!players || players.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${7 + STATS_TO_DISPLAY.length}">No players found.</td></tr>`;
            return;
        }

        players.forEach(player => {
            let totalRank = 0;
            const projections = player.per_game_projections;
            if (projections) {
                if (player.positions.includes('G')) {
                    const ranksToSum = ['w_cat_rank', 'so_cat_rank', 'svpct_cat_rank', 'gaa_cat_rank'];
                    ranksToSum.forEach(rankStat => {
                        totalRank += projections[rankStat] || 0;
                    });
                } else {
                    const ranksToSum = ['g_cat_rank', 'a_cat_rank', 'pts_cat_rank', 'ppp_cat_rank', 'hit_cat_rank', 'blk_cat_rank', 'sog_cat_rank'];
                    ranksToSum.forEach(rankStat => {
                        totalRank += projections[rankStat] || 0;
                    });
                }
            }
            // Add to object for sorting. A lower rank is better.
            player.cat_coverage_rank = totalRank;

            const statCells = STATS_TO_DISPLAY.map(stat => {
                 let colorStyle = '';
                 if (STATS_FOR_HEATMAP.includes(stat)) {
                     const rankStatName = `${stat}_cat_rank`;
                     const rank = projections ? projections[rankStatName] : null;
                     colorStyle = getRankColor(rank);
                 }
                const value = player.weekly_projections[stat] !== undefined ? player.weekly_projections[stat] : 0;
                return `<td ${colorStyle}>${value}</td>`;
            }).join('');

            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${player.name}</td>
                <td>${player.team || 'N/A'}</td>
                <td>${player.availability || 'Rostered'}</td>
                <td>${player.positions}</td>
                <td>${player.games_this_week}</td>
                <td><b>${totalRank}</b></td>
                ${statCells}
            `;
            tbody.appendChild(row);
        });
    }

    /**
     * Adds sort event listeners to a table's headers.
     * @param {HTMLTableElement} table - The table element to make sortable.
     */
    function addTableSorting(table) {
        table.querySelectorAll('thead th.sortable').forEach(headerCell => {
            if(headerCell.dataset.sortKey === currentSort.key){
                 headerCell.classList.add(currentSort.direction === 'asc' ? 'sort-asc' : 'sort-desc');
            }

            headerCell.addEventListener('click', () => {
                const sortKey = headerCell.dataset.sortKey;
                let direction = 'desc';
                // Default to ascending for Cat Coverage Rank, descending for others
                const defaultAsc = ['cat_coverage_rank', 'name', 'team', 'positions', 'availability', 'gaa'];

                if (currentSort.key === sortKey) {
                    direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
                } else {
                    direction = defaultAsc.includes(sortKey) ? 'asc' : 'desc';
                }

                table.querySelectorAll('thead th').forEach(th => th.classList.remove('sort-asc', 'sort-desc'));
                headerCell.classList.add(direction === 'asc' ? 'sort-asc' : 'sort-desc');

                currentSort = { key: sortKey, direction };
                sortAndRerenderTable(table, currentSort);
            });
        });
        sortAndRerenderTable(table, currentSort); // Initial sort
    }

    /**
     * Sorts the global player data array and re-populates the table body.
     * @param {HTMLTableElement} table - The table to update.
     * @param {object} sortConfig - { key: string, direction: 'asc'|'desc' }.
     */
    function sortAndRerenderTable(table, { key, direction }) {
        const isNumeric = !['name', 'team', 'availability', 'positions'].includes(key);
        const inverseSortStats = ['gaa']; // For these raw stats, a lower value is better

        allAvailablePlayersData.sort((a, b) => {
            let valA, valB;

            if (key === 'cat_coverage_rank') {
                valA = a.cat_coverage_rank || 999;
                valB = b.cat_coverage_rank || 999;
            } else if (isNumeric) {
                valA = a.weekly_projections[key] !== undefined ? a.weekly_projections[key] : -1;
                valB = b.weekly_projections[key] !== undefined ? b.weekly_projections[key] : -1;
            } else {
                valA = a[key] || '';
                valB = b[key] || '';
            }

            let comparison = 0;
            if (valA > valB) {
                comparison = 1;
            } else if (valA < valB) {
                comparison = -1;
            }

            // Invert comparison for stats where lower is better
            if (isNumeric && inverseSortStats.includes(key)) {
                comparison = -comparison;
            }

            return direction === 'asc' ? comparison : -comparison;
        });

        populateTableBody(table, allAvailablePlayersData);
    }


    /**
     * Main function to fetch all data and render the page.
     */
    async function fetchAndDisplayData() {
        try {
            // This API call now correctly relies on the server-side session cache.
            // We only need to pass the team_name to identify which roster to pull.
            const apiUrl = `${API_BASE_URL}/api/all-players?team_name=${encodeURIComponent(teamName)}`;
            const response = await fetch(apiUrl);
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || `HTTP error! Status: ${response.status}`);
            }
            const data = await response.json();

            // Render Roster Table (not sortable)
            rosterContainer.innerHTML = `<h2>${decodeURIComponent(teamName)}'s Roster</h2>`;
            rosterContainer.appendChild(createPlayerTable(data.team_roster, 'rosterTable', false));

            // Render Available Players Table (sortable)
            allAvailablePlayersData = data.available_players; // Store for sorting
            availablePlayersContainer.innerHTML = '<h2>Available Players (FA / Waivers)</h2>';
            const availableTable = createPlayerTable([], 'availablePlayersTable', true); // Create empty, then sort populates
            availablePlayersContainer.appendChild(availableTable);
            addTableSorting(availableTable);

        } catch (error) {
            console.error("Failed to fetch player data:", error);
            rosterContainer.innerHTML = `<p style="color: red;">Error loading roster: ${error.message}</p>`;
            availablePlayersContainer.innerHTML = `<p style="color: red;">Error loading available players: ${error.message}</p>`;
        }
    }

    fetchAndDisplayData();
});
