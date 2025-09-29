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
export function createSummaryTable(team1, totals1Full, totals1Live, team2, totals2Full, totals2Live, titleText = "Current Projected Matchup") {
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
    const inverseStats = ['gaa'];

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

export function createFreeAgentTable(freeAgents, weights) {
    const table = document.createElement('table');
    const headerStats = STATS_TO_DISPLAY_H2H.map(stat => {
        const weight = weights[stat] || 0;
        const style = weight >= 2.0 ? 'style="background-color: #ffeeba;"' : '';
        return `<th ${style}>${stat.toUpperCase()}</th>`;
    }).join('');
    table.innerHTML = `<thead><tr><th>Player</th><th>Team</th><th>Status</th><th>Positions</th><th>Games</th>${headerStats}<th>Start Days</th></tr></thead>`;

    const tbody = document.createElement('tbody');
    if (freeAgents.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${6 + STATS_TO_DISPLAY_H2H.length}">No valuable free agents found.</td></tr>`;
    } else {
        freeAgents.forEach(fa => {
            const statCells = STATS_TO_DISPLAY_H2H.map(stat => `<td>${fa.weekly_projections[stat] || 0}</td>`).join('');
            tbody.innerHTML += `
                <tr>
                    <td>${fa.name}</td>
                    <td>${fa.team}</td>
                    <td>${fa.availability || 'FA'}</td>
                    <td>${fa.positions}</td>
                    <td>${fa.games_this_week}</td>
                    ${statCells}
                    <td>${fa.start_days}</td>
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
