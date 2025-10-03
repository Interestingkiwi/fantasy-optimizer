/**
 * ui.js
 * * This module contains all functions that create or manipulate DOM elements.
 * It takes data as input and outputs HTML elements, keeping the main logic
 * clean of DOM-specific code.
 */

// --- Constants ---
const STATS_TO_DISPLAY_H2H = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk', 'w', 'so', 'svpct', 'gaa'];
const FANTASY_WEEKS = 25;
const MAX_TRANSACTIONS = 4;

// --- Helper for Heatmap ---
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
    // Use a high lightness to keep it pastel and readable, with moderate saturation.
    return `style="background-color: hsl(${hue}, 70%, 85%); color: #333;"`;
}


// --- UI State Functions ---
export function showLoginView() {
    document.getElementById('login-container').classList.remove('hidden');
    document.getElementById('main-content').classList.add('hidden');
    document.getElementById('logoutBtn').classList.add('hidden');
}

export function showMainView() {
    document.getElementById('login-container').classList.add('hidden');
    document.getElementById('main-content').classList.remove('hidden');
    document.getElementById('logoutBtn').classList.remove('hidden');
}

// --- UI Creation Functions ---
export function createSummaryTable(team1, totals1Current, totals1Live, team2, totals2Current, totals2Live, titleText = "Current Projected Matchup") {
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
                <th>${team1} (Current)</th>
                <th>${team1} (Live Proj)</th>
                <th>${team2} (Current)</th>
                <th>${team2} (Live Proj)</th>
            </tr>
        </thead>`;
    const tbody = document.createElement('tbody');
    const inverseStats = ['gaa'];

    STATS_TO_DISPLAY_H2H.forEach(stat => {
        const t1_current = totals1Current ? (totals1Current[stat] !== undefined ? totals1Current[stat] : 0) : 'N/A';
        const t1_live = totals1Live ? (totals1Live[stat] !== undefined ? totals1Live[stat] : 0) : 'N/A';
        const t2_current = totals2Current ? (totals2Current[stat] !== undefined ? totals2Current[stat] : 0) : 'N/A';
        const t2_live = totals2Live ? (totals2Live[stat] !== undefined ? totals2Live[stat] : 0) : 'N/A';

        const isInverse = inverseStats.includes(stat);
        let current1_style = '', current2_style = '', live1_style = '', live2_style = '';

        if (t1_current !== 'N/A' && t2_current !== 'N/A') {
            if ((!isInverse && t1_current > t2_current) || (isInverse && t1_current < t2_current)) {
                current1_style = 'background-color: #d4edda;'; // Green for team 1 win
                current2_style = 'background-color: #f8d7da;'; // Red for team 2 loss
            } else if ((!isInverse && t2_current > t1_current) || (isInverse && t2_current < t1_current)) {
                current2_style = 'background-color: #d4edda;'; // Green for team 2 win
                current1_style = 'background-color: #f8d7da;'; // Red for team 1 loss
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
                <td style="${current1_style}">${t1_current}</td>
                <td style="${live1_style}">${t1_live}</td>
                <td style="${current2_style}">${t2_current}</td>
                <td style="${live2_style}">${t2_live}</td>
            </tr>`;
    });
    table.appendChild(tbody);
    container.appendChild(table);
    return container;
}

export function createOffDaysSection(offDays) {
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

export function createUtilizationTable(roster, titleText) {
    const container = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = titleText;
    container.appendChild(title);

    const table = document.createElement('table');
    table.innerHTML = `<thead><tr><th>Player</th><th>Positions</th><th>Games</th><th>Starts</th><th>Util %</th><th>Start Days</th><th>Team Games</th></tr></thead>`;
    const tbody = document.createElement('tbody');
    roster.sort((a, b) => b.starts_this_week - a.starts_this_week);
    roster.forEach(player => {
        const games = player.games_this_week, starts = player.starts_this_week;
        const util = games > 0 ? `${((starts / games) * 100).toFixed(0)}%` : 'N/A';
        const row = document.createElement('tr');
        row.innerHTML = `<td>${player.name}</td><td>${player.positions}</td><td>${games}</td><td>${starts}</td><td>${util}</td><td>${player.start_days || ''}</td><td>${player.team_game_days || ''}</td>`;
        if (games > 0 && starts < games) row.style.backgroundColor = '#fff5f5';
        tbody.appendChild(row);
    });
    table.appendChild(tbody);
    container.appendChild(table);
    return container;
}

export function createOpenSlotsTable(slotsByDay) {
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

export function createGoalieScenariosTable(data) {
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
    tbody.innerHTML = `
        <tr style="font-weight: bold;">
            <td>Current Stats</td>
            <td>${data.current_gaa.toFixed(3)}</td>
            <td>${data.current_svpct.toFixed(3)}</td>
        </tr>
    `;
    data.scenarios.forEach(s => {
        tbody.innerHTML += `
            <tr>
                <td>${s.name}</td>
                <td>${s.gaa}</td>
                <td>${s.svpct.toFixed(3)}</td>
            </tr>
        `;
    });
    table.appendChild(tbody);
    container.appendChild(table);
    return container;
}

export function createOptimizerSection(title, players, isStarting = true) {
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

export function createOptimizerTable(players, isStarting) {
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

export function createOptimizerContextSection(title, context) {
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

/**
 * Formats a comma-separated string of day abbreviations to bold any back-to-back days.
 * @param {string} dayString - e.g., "Mon, Tue, Fri"
 * @returns {string} HTML string with <b> tags, e.g., "<b>Mon</b>, <b>Tue</b>, Fri"
 */
function formatBackToBackDays(dayString) {
    if (!dayString) return '';
    const days = dayString.split(', ');
    if (days.length < 2) return dayString;

    const dayOrder = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    // Create a set for quick lookups
    const daySet = new Set(days);

    const formattedDays = days.map(day => {
        const dayIndex = dayOrder.indexOf(day);
        const prevDay = dayIndex > 0 ? dayOrder[dayIndex - 1] : null;
        const nextDay = dayIndex < 6 ? dayOrder[dayIndex + 1] : null;

        const isB2B = (prevDay && daySet.has(prevDay)) || (nextDay && daySet.has(nextDay));

        return isB2B ? `<b>${day}</b>` : day;
    });

    return formattedDays.join(', ');
}

export function createFreeAgentTable(freeAgents, weights) {
    const table = document.createElement('table');
    const statsForHeatmap = ['g', 'a', 'pts', 'ppp', 'sog', 'hit', 'blk'];

    const headerStats = STATS_TO_DISPLAY_H2H.map(stat => {
        const weight = weights[stat] || 0;
        const style = weight >= 2.0 ? 'style="background-color: #ffeeba;"' : '';
        return `<th ${style}>${stat.toUpperCase()}</th>`;
    }).join('');
    table.innerHTML = `<thead><tr><th>Player</th><th>Team</th><th>Status</th><th>Positions</th><th>Games</th><th>Total Rank</th>${headerStats}<th>Start Days</th><th>Next Week Starts</th></tr></thead>`;

    const tbody = document.createElement('tbody');
    if (freeAgents.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${9 + STATS_TO_DISPLAY_H2H.length}">No valuable free agents found.</td></tr>`;
    } else {
        freeAgents.forEach(fa => {
            const ranksToSum = ['g_cat_rank', 'a_cat_rank', 'pts_cat_rank', 'ppp_cat_rank', 'hit_cat_rank', 'blk_cat_rank', 'sog_cat_rank'];
            let totalRank = 0;
            if (fa.per_game_projections) {
                ranksToSum.forEach(rankStatName => {
                    totalRank += fa.per_game_projections[rankStatName] || 0;
                });
            }

            const statCells = STATS_TO_DISPLAY_H2H.map(stat => {
                let colorStyle = '';
                if (statsForHeatmap.includes(stat)) {
                    const rankStatName = `${stat}_cat_rank`;
                    // The rank data is in per_game_projections, not weekly_projections
                    const rank = fa.per_game_projections ? fa.per_game_projections[rankStatName] : null;
                    colorStyle = getRankColor(rank);
                }
                const value = fa.weekly_projections[stat] !== undefined ? fa.weekly_projections[stat] : 0;
                return `<td ${colorStyle}>${value}</td>`;
            }).join('');

            const formattedStartDays = formatBackToBackDays(fa.start_days);
            const formattedNextWeekStarts = formatBackToBackDays(fa.next_week_starts);

            tbody.innerHTML += `
                <tr>
                    <td>${fa.name}</td>
                    <td>${fa.team}</td>
                    <td>${fa.availability || 'FA'}</td>
                    <td>${fa.positions}</td>
                    <td>${fa.games_this_week}</td>
                    <td><b>${totalRank}</b></td>
                    ${statCells}
                    <td>${formattedStartDays}</td>
                    <td>${formattedNextWeekStarts}</td>
                </tr>`;
        });
    }
    table.appendChild(tbody);
    return table;
}


export function createFreeAgentPagination(startIndex, resultCount, onPageChange) {
    const div = document.createElement('div');
    div.className = 'pagination-controls';
    const prevBtn = document.createElement('button');
    prevBtn.textContent = '<< Previous';
    prevBtn.disabled = startIndex === 0;
    prevBtn.addEventListener('click', () => onPageChange(startIndex - 20));

    const nextBtn = document.createElement('button');
    nextBtn.textContent = 'Next >>';
    nextBtn.disabled = resultCount < 20;
    nextBtn.addEventListener('click', () => onPageChange(startIndex + 20));

    div.appendChild(prevBtn);
    div.appendChild(nextBtn);
    return div;
}

export function createPlayerTable(rosterData, statToDisplay) {
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

export function createTransactionRows(container) {
    for (let i = 0; i < MAX_TRANSACTIONS; i++) {
        const row = document.createElement('div');
        row.className = 'transaction-row';
        row.innerHTML = `
            <label>Add:</label> <select id="add-player-${i}"><option value="">-- Select Player --</option></select>
            <label>Drop:</label> <select id="drop-player-${i}"><option value="">-- Select Player --</option></select>
            <label>Date:</label> <input type="date" id="trans-date-${i}">
        `;
        container.appendChild(row);
    }
}

// --- UI Population Functions ---

export function populateLeagueSelector(selector, leagues) {
    selector.innerHTML = '<option value="">-- Select a League --</option>';
    if (leagues && leagues.length > 0) {
        leagues.forEach(league => {
            selector.add(new Option(`${league.name} (${league.league_id})`, league.league_id));
        });
    }
}

export function populateWeekSelector(selector) {
    for (let i = 1; i <= FANTASY_WEEKS; i++) {
        selector.add(new Option(`Week ${i}`, i));
    }
}

export function populateTeamSelectors(myTeamSel, opponentSel, rosters) {
    const teamNames = Object.keys(rosters);
    [myTeamSel, opponentSel].forEach(sel => {
        const currentVal = sel.value;
        sel.innerHTML = '';
        teamNames.forEach(name => sel.add(new Option(name, name)));
        sel.value = currentVal;
    });
    if (myTeamSel.value === opponentSel.value && teamNames.length > 1) {
        opponentSel.value = teamNames.find(name => name !== myTeamSel.value);
    }
}

// --- UI Utility Functions ---

export function showLoading(container, message) {
    if (container.tagName === 'SELECT') {
        container.innerHTML = `<option>${message}</option>`;
    } else {
        container.innerHTML = `<p>${message}</p>`;
    }
}

export function showError(container, message) {
    container.innerHTML = `<p style="color: red;">Error: ${message}</p>`;
}

export function clearAllSections(containersToClear) {
    containersToClear.forEach(container => {
        if (container) container.innerHTML = '';
    });
}
