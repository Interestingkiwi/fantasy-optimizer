(async function() {
    // Wait for the DOM to be fully loaded before running
    await new Promise(resolve => {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", resolve);
        } else {
            resolve();
        }
    });

    const errorDiv = document.getElementById('db-error-message');
    const weekSelect = document.getElementById('history-week-select');
    const yourTeamSelect = document.getElementById('your-team-select');
    const reportSelect = document.getElementById('history-report-select');
    const historyContent = document.getElementById('history-content');
    const loadingSpinner = document.getElementById('loading-spinner');

    const viewToggleButton = document.getElementById('view-toggle-button');
    // --- MODIFIED: Remove teamSelectWrapper ---
    // const teamSelectWrapper = document.getElementById('team-select-wrapper');
    let currentViewMode = 'team'; // 'team' or 'league'
    // --- END MODIFIED ---

    let pageData = null;

    function showError(message) {
        errorDiv.textContent = message;
        errorDiv.classList.remove('hidden');
        historyContent.innerHTML = ''; // Clear content on error
        loadingSpinner.classList.add('hidden');
    }

    async function fetchPageData() {
        try {
            const response = await fetch('/api/season_history_page_data');
            if (!response.ok) {
                throw new Error(`Failed to load page data. Server responded with ${response.status}`);
            }
            const data = await response.json();
            if (!data.db_exists) {
                showError(data.error || "Database not found. Please create one on the 'League Database' page.");
                return false;
            }
            pageData = data; // Store data globally for this module
            return true;
        } catch (error) {
            console.error('Error fetching page data:', error);
            showError(`Error fetching page data: ${error.message}`);
            return false;
        }
    }

    function populateDropdowns() {
        // --- Team Dropdown --- (Handled by home.js)

        // --- Week Dropdown ---
        const completedWeeks = pageData.weeks.filter(week => week.week_num < pageData.current_week);
        let weekOptions = '<option value="all">All Season</option>';
        weekOptions += completedWeeks.map(week =>
            `<option value="${week.week_num}">
                Week ${week.week_num} (${week.start_date} to ${week.end_date})
            </option>`
        ).join('');
        weekSelect.innerHTML = weekOptions;
        weekSelect.value = "all"; // Default to "All Season"

        // --- Report Dropdown ---
        let reportOptions = '';
        reportOptions += '<option value="please_select">--Please Select--</option>'; // Your default
        reportOptions += '<option value="bench_points">Bench Points</option>';
        reportOptions += '<option value="transaction_history">Transaction History</option>';
        reportOptions += '<option value="category_strengths">Category Strengths</option>';
        reportOptions += '<option value="tbd">TBD</option>';

        reportSelect.innerHTML = reportOptions;
    }

    function setupEventListeners() {
        weekSelect.addEventListener('change', fetchAndRenderTable);
        yourTeamSelect.addEventListener('change', fetchAndRenderTable);
        reportSelect.addEventListener('change', handleReportChange);
        viewToggleButton.addEventListener('click', toggleViewMode);
    }

    // --- MODIFIED: Removed teamSelectWrapper logic ---
    function handleReportChange() {
        const selectedReport = reportSelect.value;
        if (selectedReport === 'transaction_history') {
            viewToggleButton.classList.remove('hidden');
            // Restore view state
            updateControlsForViewMode();
        } else {
            viewToggleButton.classList.add('hidden');
            // --- REMOVED ---
            // teamSelectWrapper.classList.remove('hidden');
        }
        fetchAndRenderTable();
    }
    // --- END MODIFIED ---

    function toggleViewMode() {
        currentViewMode = (currentViewMode === 'team') ? 'league' : 'team';
        updateControlsForViewMode();
        fetchAndRenderTable();
    }

    // --- MODIFIED: Removed teamSelectWrapper logic ---
    function updateControlsForViewMode() {
        if (currentViewMode === 'league') {
            viewToggleButton.textContent = 'Switch to Team View';
            viewToggleButton.classList.replace('bg-blue-600', 'bg-indigo-600');
            viewToggleButton.classList.replace('hover:bg-blue-700', 'hover:bg-indigo-700');
            // --- REMOVED ---
            // teamSelectWrapper.classList.add('hidden');

            // --- NEW: Disable "All Season" in league view ---
            if (weekSelect.value === 'all') {
                weekSelect.value = pageData.weeks.filter(w => w.week_num < pageData.current_week)[0]?.week_num || '1';
            }
            weekSelect.querySelector('option[value="all"]').disabled = true;

        } else { // 'team' view
            viewToggleButton.textContent = 'Switch to League View';
            viewToggleButton.classList.replace('bg-indigo-600', 'bg-blue-600');
            viewToggleButton.classList.replace('hover:bg-indigo-700', 'hover:bg-blue-700');
            // --- REMOVED ---
            // teamSelectWrapper.classList.remove('hidden');
            weekSelect.querySelector('option[value="all"]').disabled = false; // Re-enable "All Season"
        }
    }
    // --- END MODIFIED ---


    // --- Helper function to create a table ---
    function createTable(title, headers, rows) {
        let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                        <h3 class="text-lg font-semibold text-white mb-3">${title}</h3>`;

        if (rows.length === 0) {
            html += '<p class="text-gray-400">No data found for this period.</p></div>';
            return html;
        }

        html += `<div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead>
                            <tr>
                                <th class="table-header">Date</th>
                                <th class="table-header">Player</th>
                                <th class="table-header">Positions</th>
                                `;

        // Filter headers to only include those with data
        const headersWithData = headers.filter(header =>
            rows.some(row => row[header] && row[header] != 0)
        );

        for (const header of headersWithData) {
            html += `<th class="table-header">${header}</th>`;
        }

        html += `           </tr>
                        </thead>
                        <tbody class="bg-gray-900 divide-y divide-gray-700">`;

        for (const row of rows) {
            html += `<tr>
                        <td class="table-cell text-center">${row['Date']}</td>
                        <td class="table-cell text-center">${row['Player']}</td>
                        <td class="table-cell text-center">${row['Positions'] || ''}</td>
                        `;
            for (const header of headersWithData) {
                html += `<td class="table-cell text-center">${row[header] || 0}</td>`;
            }
            html += `</tr>`;
        }

        html += `       </tbody>
                    </table>
                </div>
            </div>`;
        return html;
    }


    function createMatchupStatsTable(matchup_data) {
            const { your_team_stats, opponent_team_stats, opponent_name, scoring_categories } = matchup_data;

            // --- START NEW LOGIC ---
            // 1. Define goalie sub-category relationships
            const goalieCats = {
                'SVpct': ['SV', 'SA'],
                'GAA': ['GA', 'TOI/G']
            };
            const scoringCategoriesSet = new Set(scoring_categories);

            // 2. Create a set of categories to skip in the main loop
            const catsToSkip = new Set();
            if (scoringCategoriesSet.has('SVpct')) {
                goalieCats['SVpct'].forEach(cat => catsToSkip.add(cat));
            }
            if (scoringCategoriesSet.has('GAA')) {
                goalieCats['GAA'].forEach(cat => catsToSkip.add(cat));
            }
            // --- END NEW LOGIC ---

            let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                            <h3 class="text-lg font-semibold text-white mb-3">Matchup Result</h3>
                            <h4 class="text-sm text-gray-400 mb-3 -mt-2">vs. ${opponent_name}</h4>
                            <div class="overflow-x-auto">
                                <table class="min-w-full">
                                    <thead>
                                        <tr>
                                            <th class="table-header !text-left">Category</th>
                                            <th class="table-header">You</th>
                                            <th class="table-header">Opp</th>
                                        </tr>
                                    </thead>
                                    <tbody class="bg-gray-900 divide-y divide-gray-700">`;

            for (const category of scoring_categories) {

                // --- START MODIFIED LOGIC ---
                // 3. Skip rendering this category if it's a sub-category of one that exists
                if (catsToSkip.has(category)) {
                    continue;
                }
                // --- END MODIFIED LOGIC ---

                const your_val = your_team_stats[category] || 0;
                const opp_val = opponent_team_stats[category] || 0;

                // Add styling for wins/losses
                let your_class = 'text-gray-400';
                let opp_class = 'text-gray-400';

                // Handle reverse-scoring categories (GAA, GA)
                if (['GAA', 'GA'].includes(category)) {
                    if (your_val < opp_val) {
                        your_class = 'text-green-400 font-bold';
                    } else if (opp_val < your_val) {
                        opp_class = 'text-green-400 font-bold';
                    }
                } else { // Handle normal scoring
                    if (your_val > opp_val) {
                        your_class = 'text-green-400 font-bold';
                    } else if (opp_val > your_val) {
                        opp_class = 'text-green-400 font-bold';
                    }
                }

                // 4. Render the main category row (with a style fix to make winning cats bold)
                html += `<tr>
                            <td class="table-cell !text-left ${your_class.includes('font-bold') ? 'font-semibold' : ''}">${category}</td>
                            <td class="table-cell text-center ${your_class}">${your_val}</td>
                            <td class="table-cell text-center ${opp_class}">${opp_val}</td>
                           </tr>`;

                // --- START NEW LOGIC ---
                // 5. Check for and render sub-categories
                if (goalieCats.hasOwnProperty(category)) {
                    for (const subCat of goalieCats[category]) {
                        // Get sub-cat values (no win/loss styling)
                        const your_sub_val = your_team_stats[subCat] || 0;
                        const opp_sub_val = opponent_team_stats[subCat] || 0;

                        html += `<tr class="hover:bg-gray-700/50">
                                    <td class="table-cell !text-left pl-8 text-sm text-gray-400">${subCat}</td>
                                    <td class="table-cell text-center text-sm text-gray-400">${your_sub_val}</td>
                                    <td class="table-cell text-center text-sm text-gray-400">${opp_sub_val}</td>
                                </tr>`;
                    }
                }
                // --- END NEW LOGIC ---
            }

            html += `           </tbody>
                            </table>
                        </div>
                    </div>`;
            return html;
        }


        function createOptimizedMatchupTable(optimized_data, original_data) {

            const { your_team_stats, opponent_team_stats, opponent_name, scoring_categories } = optimized_data;
            const original_your_stats = original_data.your_team_stats;

            // --- Define goalie sub-category relationships ---
            const goalieCats = {
                'SVpct': ['SV', 'SA'],
                'GAA': ['GA', 'TOI/G']
            };
            const scoringCategoriesSet = new Set(scoring_categories);
            const catsToSkip = new Set();
            if (scoringCategoriesSet.has('SVpct')) {
                goalieCats['SVpct'].forEach(cat => catsToSkip.add(cat));
            }
            if (scoringCategoriesSet.has('GAA')) {
                goalieCats['GAA'].forEach(cat => catsToSkip.add(cat));
            }

            // --- Helper function for scoring ---
            const getPoints = (my_val, opp_val, is_reverse) => {
                if ((my_val > opp_val && !is_reverse) || (my_val < opp_val && is_reverse)) {
                    return 2; // Win
                }
                if (my_val === opp_val) {
                    return 1; // Tie
                }
                return 0; // Loss
            };

            let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                            <h3 class="text-lg font-semibold text-white mb-3">Maximized Result (What If)</h3>
                            <h4 class="text-sm text-gray-400 mb-3 -mt-2">vs. ${opponent_name}</h4>
                            <div class="overflow-x-auto">
                                <table class="min-w-full">
                                    <thead>
                                        <tr>
                                            <th class="table-header !text-left">Category</th>
                                            <th class="table-header">You (Opt)</th>
                                            <th class="table-header">Opp</th>
                                        </tr>
                                    </thead>
                                    <tbody class="bg-gray-900 divide-y divide-gray-700">`;

            for (const category of scoring_categories) {
                if (catsToSkip.has(category)) continue;

                const your_val = your_team_stats[category] || 0;
                const opp_val = opponent_team_stats[category] || 0;
                const original_val = original_your_stats[category] || 0;

                const is_reverse = ['GAA', 'GA'].includes(category);

                // --- Calculate points for highlighting ---
                const original_points = getPoints(original_val, opp_val, is_reverse);
                const new_points = getPoints(your_val, opp_val, is_reverse);

                let highlight_class = '';
                if (new_points > original_points) {
                    if (new_points === 2) highlight_class = 'bg-green-600/30'; // Became a Win
                    else if (new_points === 1) highlight_class = 'bg-yellow-600/30'; // Became a Tie
                } else if (new_points < original_points) {
                    highlight_class = 'bg-red-600/30'; // Became a Loss
                }

                // --- Get win/loss text styling ---
                let your_class = 'text-gray-400';
                let opp_class = 'text-gray-400';

                if (is_reverse) {
                    if (your_val < opp_val) your_class = 'text-green-400 font-bold';
                    else if (opp_val < your_val) opp_class = 'text-green-400 font-bold';
                } else {
                    if (your_val > opp_val) your_class = 'text-green-400 font-bold';
                    else if (opp_val > your_val) opp_class = 'text-green-400 font-bold';
                }

                // --- Render the main category row ---
                html += `<tr class="${highlight_class}">
                            <td class="table-cell !text-left ${your_class.includes('font-bold') ? 'font-semibold' : ''}">${category}</td>
                            <td class="table-cell text-center ${your_class}">${your_val}</td>
                            <td class="table-cell text-center ${opp_class}">${opp_val}</td>
                           </tr>`;

                // --- Render sub-categories (no highlighting) ---
                if (goalieCats.hasOwnProperty(category)) {
                    for (const subCat of goalieCats[category]) {
                        const your_sub_val = your_team_stats[subCat] || 0;
                        const opp_sub_val = opponent_team_stats[subCat] || 0;
                        html += `<tr class="hover:bg-gray-700/50">
                                    <td class="table-cell !text-left pl-8 text-sm text-gray-400">${subCat}</td>
                                    <td class="table-cell text-center text-sm text-gray-400">${your_sub_val}</td>
                                    <td class="table-cell text-center text-sm text-gray-400">${opp_sub_val}</td>
                                </tr>`;
                    }
                }
            }
            html += `           </tbody>
                            </table>
                        </div>
                    </div>`;
            return html;
        }


        function createSwapsStatTable(swaps_log, skater_headers, goalie_headers) {
            const all_headers = [...skater_headers, ...goalie_headers];

            // Filter headers to only those that actually changed
            const headers_with_changes = all_headers.filter(header =>
                swaps_log.some(swap => swap.stat_diffs[header])
            );

            let html = `<div class"bg-gray-800 rounded-lg shadow-lg p-4">
                            <h3 class="text-lg font-semibold text-white mb-3">Ideal Roster</h3>`;

            if (swaps_log.length === 0) {
                html += '<p class="text-gray-400">No beneficial swaps were found.</p></div>';
                return html;
            }

            html += `<div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-700">
                            <thead>
                                <tr>
                                    <th class="table-header">Date</th>
                                    <th class="table-header">Bench Player</th>
                                    <th class="table-header">Replaced Player</th>
                                    `;

            // Create headers
            for (const header of headers_with_changes) {
                html += `<th class="table-header">${header}</th>`;
            }

            html += `       </tr>
                            </thead>
                            <tbody class="bg-gray-900 divide-y divide-gray-700">`;

            const totals = {};

            // Create data rows
            for (const swap of swaps_log) {
                html += `<tr>
                            <td class="table-cell text-center">${swap.date}</td>
                            <td class="table-cell text-center text-green-400">${swap.bench_player}</td>
                            <td class="table-cell text-center text-red-400">${swap.replaced_player}</td>
                           `;

                for (const header of headers_with_changes) {
                    const diff = swap.stat_diffs[header] || 0;

                    // Add to totals
                    totals[header] = (totals[header] || 0) + diff;

                    // Format the diff
                    let diff_text = diff === 0 ? '0' : (diff > 0 ? `+${diff}` : `${diff}`);
                    let diff_class = diff > 0 ? 'text-green-400' : (diff < 0 ? 'text-red-400' : 'text-gray-500');

                    html += `<td class="table-cell text-center ${diff_class}">${diff_text}</td>`;
                }
                html += `</tr>`;
            }

            // --- Create Total Row ---
            html += `<tr class="border-t-2 border-gray-500">
                        <td class="table-cell text-center font-bold">Total</td>
                        <td class="table-cell"></td>
                        <td class="table-cell"></td>
                       `;

            for (const header of headers_with_changes) {
                const total_diff = totals[header] || 0;

                let diff_text = total_diff === 0 ? '0' : (total_diff > 0 ? `+${total_diff}` : `${total_diff}`);
                let diff_class = total_diff > 0 ? 'text-green-400' : (total_diff < 0 ? 'text-red-400' : 'text-gray-500');

                html += `<td class="table-cell text-center ${diff_class} font-bold">${diff_text}</td>`;
            }

            html += `       </tr>
                            </tbody>
                        </table>
                    </div>
                </div>`;
            return html;
        }


    // --- Function to fetch and render bench points ---
    async function fetchBenchPoints(teamName, week) {
        loadingSpinner.classList.remove('hidden');
        historyContent.innerHTML = '';
        errorDiv.classList.add('hidden');

        try {
            const response = await fetch('/api/history/bench_points', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ team_name: teamName, week: week })
            });

            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            // Render the two bench tables
            const skaterTable = createTable('Skaters', data.skater_headers, data.skater_data);
            const goalieTable = createTable('Goalies', data.goalie_headers, data.goalie_data);

            // --- START MODIFIED LAYOUT ---
            let matchupHtml = '';
            let optimizedHtml = '';
            let swapsHtml = ''; // This will now go to the left column

            if (data.matchup_data) {
                // If matchup data exists, render the original table
                matchupHtml = createMatchupStatsTable(data.matchup_data);

                // Render the new "Optimized" table
                optimizedHtml = createOptimizedMatchupTable(data.optimized_matchup_data, data.matchup_data);

                // --- Render the new "Swaps Stat Table" ---
                swapsHtml = createSwapsStatTable(data.swaps_log, data.skater_headers, data.goalie_headers);

            } else {
                // Otherwise, show the "All Season" message
                matchupHtml = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                                    <h3 class="text-lg font-semibold text-white mb-3">Matchup Result</h3>
                                    <p class="text-gray-400">Matchup outcome unavailable when "All Season" is selected.</p>
                                   </div>`;
            }

            // --- New Layout Structure ---
            historyContent.innerHTML = `
                <div class="flex flex-col lg:flex-row gap-6">

                    <div class="flex-grow space-y-6">
                        ${skaterTable}
                        ${goalieTable}
                        ${swapsHtml}
                    </div>

                    <div class="w-full lg:w-2/5 xl:w-1/2 flex-shrink-0 space-y-6">

                        <div class="flex flex-col lg:flex-row gap-6">
                            <div class="w-full lg:w-1/2">
                                ${matchupHtml}
                            </div>
                            <div class="w-full lg:w-1/2">
                                ${optimizedHtml}
                            </div>
                        </div>

                    </div>

                </div>
            `;
            // --- END MODIFIED LAYOUT ---

        } catch (error) {
            console.error('Error fetching bench points:', error);
            showError(error.message);
        } finally {
            loadingSpinner.classList.add('hidden');
        }
    }

    // --- Helper function to create a simple transaction table ---
    function createTransactionTable(title, rows) {
        let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                        <h3 class="text-lg font-semibold text-white mb-3">${title}</h3>`;

        if (!rows || rows.length === 0) {
            html += '<p class="text-gray-400">No transactions found for this period.</p></div>';
            return html;
        }

        html += `<div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead>
                            <tr>
                                <th class="table-header !text-left">Date</th>
                                <th class="table-header !text-left">Player</th>
                            </tr>
                        </thead>
                        <tbody class="bg-gray-900 divide-y divide-gray-700">`;

        for (const row of rows) {
            html += `<tr>
                        <td class="table-cell !text-left">${row['transaction_date']}</td>
                        <td class="table-cell !text-left">${row['player_name']}</td>
                       </tr>`;
        }

        html += `       </tbody>
                    </table>
                </div>
            </div>`;
        return html;
    }


    // --- Helper function to create the added player stats table ---
    // --- MODIFIED: To handle Goalie calculated stats (SVpct, GAA) ---
    function createAddedPlayerStatsTable(title, headers = [], rows = []) {
        let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                        <h3 class="text-lg font-semibold text-white mb-3">${title}</h3>`;

        if (rows.length === 0) {
            html += `<p class="text-gray-400">No ${title.toLowerCase()} found or no stats recorded.</p></div>`;
            return html;
        }

        // --- NEW: Goalie sub-category logic ---
        const goalieCats = {
            'SVpct': ['SV', 'SA'],
            'GAA': ['GA', 'TOI/G']
        };
        const headersSet = new Set(headers);
        const catsToSkip = new Set();
        if (headersSet.has('SVpct')) {
            goalieCats['SVpct'].forEach(cat => catsToSkip.add(cat));
        }
        if (headersSet.has('GAA')) {
            goalieCats['GAA'].forEach(cat => catsToSkip.add(cat));
        }
        // --- END NEW ---

        html += `<div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead>
                            <tr>
                                <th class="table-header !text-left">Player</th>
                                <th class="table-header">GP</th>
                                `;

        // Use all headers provided by the server, but filter out skipped sub-cats
        const headersToDisplay = headers.filter(h => h !== 'GP' && !catsToSkip.has(h));

        for (const header of headersToDisplay) {
            html += `<th class="table-header">${header}</th>`;
        }

        html += `           </tr>
                        </thead>
                        <tbody class="bg-gray-900 divide-y divide-gray-700">`;

        for (const row of rows) {
            html += `<tr>
                        <td class="table-cell !text-left">${row['Player']}</td>
                        <td class="table-cell text-center">${row['GP'] || 0}</td>
                        `;

            for (const header of headersToDisplay) {
                let value = row[header] || 0;
                let displayHtml = '';

                // --- NEW: Formatting for calculated stats ---
                if (header === 'SVpct') {
                    const sv = row['SV'] || 0;
                    const sa = row['SA'] || 0;
                    displayHtml = `${value.toFixed(3)}
                                 <br><span class="text-xs text-gray-400">(${sv}/${sa})</span>`;
                } else if (header === 'GAA') {
                    const ga = row['GA'] || 0;
                    const toi = row['TOI/G'] || 0;
                    // Format TOI to 2 decimals if it's not an integer, otherwise just show it
                    const toiDisplay = Number.isInteger(toi) ? toi : toi.toFixed(2);
                    displayHtml = `${value.toFixed(2)}
                                 <br><span class="text-xs text-gray-400">(${ga} GA / ${toiDisplay} TOI)</span>`;
                } else {
                    // Format other numbers to 2 decimals if they are floats
                    displayHtml = Number.isInteger(value) ? value : value.toFixed(2);
                }
                // --- END NEW ---

                html += `<td class="table-cell text-center align-middle">${displayHtml}</td>`;
            }
            html += `</tr>`;
        }

        html += `       </tbody>
                    </table>
                </div>
            </div>`;
        return html;
    }


    function createDynamicCategoryTable(title, teamHeaders, statRows) {
        let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                        <h3 class="text-lg font-semibold text-white mb-3">${title}</h3>`;

        if (!statRows || statRows.length === 0 || !teamHeaders || teamHeaders.length === 0) {
            html += '<p class="text-gray-400">No stats found for this period.</p></div>';
            return html;
        }

        html += `<div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead>
                            <tr>
                                <th class="table-header !text-left">Category</th>`;

        // (Header loop is unchanged)
        for (const teamName of teamHeaders) {
            const headerClass = (teamName === teamHeaders[0]) ? "!text-yellow-400" : "";
            html += `<th class="table-header ${headerClass}">${teamName}</th>`;

            if (teamName === teamHeaders[0]) {
                html += `<th class="table-header">Rank</th>`;
                html += `<th class="table-header">Avg Delta</th>`;
            }
        }

        html += `           </tr>
                        </thead>
                        <tbody class="bg-gray-900 divide-y divide-gray-700">`;

        // Create a row for each category
        for (const categoryRow of statRows) {
            html += `<tr>
                        <td class="table-cell !text-left font-semibold">${categoryRow.category}</td>`;

            // --- MODIFIED: Add dark text class to heatmap cells ---
            for (const teamName of teamHeaders) {
                // Get the base cell class (for user's column)
                const baseCellClass = (teamName === teamHeaders[0]) ? "text-yellow-400" : "";

                // Get the pre-calculated color
                const bgColor = (categoryRow.heatmapColors && categoryRow.heatmapColors[teamName])
                                ? categoryRow.heatmapColors[teamName]
                                : '';

                // --- FIX: Add font-semibold and text-gray-800 for dark text ---
                // This mimics the 'text-gray-600' from lineups.js
                html += `<td class="table-cell text-center font-semibold text-gray-800" style="background-color: ${bgColor};">
                            ${categoryRow[teamName]}
                         </td>`;
                // --- END FIX ---

                // This part is for Rank and Avg Delta (no heatmap)
                if (teamName === teamHeaders[0]) {
                    // We *keep* the yellow text for the Rank column
                    html += `<td class="table-cell text-center ${baseCellClass}">${categoryRow['Rank']}</td>`;
                    html += `<td class="table-cell text-center">${formatDelta(categoryRow['Average Delta'])}</td>`;
                }
            }
            // --- END MODIFICATION ---
            html += `</tr>`;
        }

        html += `       </tbody>
                    </table>
                </div>
            </div>`;
        return html;
    }


        function formatDelta(delta) {
                if (delta > 0) {
                    return `<span class="text-green-400">+${delta.toFixed(2)}</span>`;
                } else if (delta < 0) {
                    return `<span class="text-red-400">${delta.toFixed(2)}</span>`;
                }
                return `<span class="text-gray-500">0.00</span>`;
            }


            /**
         * Pre-calculates heatmap colors for each row and stores them
         * in a `heatmapColors` object on the row itself.
         * USES HSL logic from lineups.js (based on RANK, not value)
         */
        function addHeatmapData(statRows, teamHeaders) {
            // Define reverse-scoring categories here
            const reverseScoringCats = new Set(['GA', 'GAA']);

            // Define the rank range. Min is always 1. Max is number of teams.
            const minRank = 1;
            const maxRank = teamHeaders.length; // e.g., 12 teams

            for (const row of statRows) {
                const cat = row.category;
                const isReverse = reverseScoringCats.has(cat);

                // 1. Get all values and map them to objects { teamName, value }
                //    This is necessary to sort them while keeping track of the team.
                const teamValues = teamHeaders.map(teamName => ({
                    teamName: teamName,
                    value: row[teamName]
                }));

                // 2. Sort the values to determine rank
                teamValues.sort((a, b) => {
                    if (isReverse) {
                        return a.value - b.value; // Low is better
                    }
                    return b.value - a.value; // High is better
                });

                // 3. Create a map of { teamName: rank }
                const teamRanks = {};
                let currentRank = 1;
                for (let i = 0; i < teamValues.length; i++) {
                    const teamName = teamValues[i].teamName;

                    // Handle ties: if value is same as previous, give same rank
                    if (i > 0 && teamValues[i].value === teamValues[i-1].value) {
                        teamRanks[teamName] = teamRanks[teamValues[i-1].teamName];
                    } else {
                        currentRank = i + 1;
                        teamRanks[teamName] = currentRank;
                    }
                }

                row.heatmapColors = {}; // Create object to store colors

                // 4. Calculate color for each team BASED ON ITS RANK
                for (const teamName of teamHeaders) {
                    const rank = teamRanks[teamName]; // Get the team's rank (e.g., 1, 2, 5...)

                    // 5. Calculate normalized percentage (t) based on RANK, not value
                    //    This is the logic from lineups.js
                    //    A rank of 1 (best) will be 0%. A rank of 12 (worst) will be 100%.
                    let percentage = 0.5; // Default for 1-team league
                    if (maxRank > minRank) {
                        const clampedRank = Math.max(minRank, Math.min(rank, maxRank));
                        percentage = (clampedRank - minRank) / (maxRank - minRank);
                    }

                    // 6. Calculate HSL color (same as lineups.js)
                    //    We want green (hue 120) at 0% (best rank)
                    //    and red (hue 0) at 100% (worst rank).
                    const hue = (1 - percentage) * 120;

                    const color = `hsl(${hue}, 65%, 75%)`;

                    row.heatmapColors[teamName] = color;
                }
            }
        }


        /**
             * Formats a rank and its delta into the "Rank (Delta)" string.
             * e.g., 2 (-), 4 (+1), 1 (-2)
             */
            function formatRankDelta(rank, delta) {
                if (rank === null || rank === undefined) {
                    return '<span class="text-gray-500">-</span>';
                }

                let deltaStr = '(-)';
                let deltaClass = 'text-gray-500';

                if (delta !== null && delta !== undefined && delta !== 0) {
                    if (delta > 0) { // Rank improved (e.g., 4 -> 1, delta = +3)
                        deltaStr = `(+${delta})`;
                        deltaClass = 'text-green-400';
                    } else { // Rank worsened (e.g., 1 -> 4, delta = -3)
                        deltaStr = `(${delta})`;
                        deltaClass = 'text-red-400';
                    }
                }

                return `${rank} <span class="${deltaClass}">${deltaStr}</span>`;
            }

            /**
             * Creates the "All Season" trend table (Matrix)
             */
            function createRankTrendMatrixTable(categories, trendData) {
                const weeks = trendData.weeks;
                const matrixData = trendData.data;

                if (weeks.length === 0) {
                    return '<div class="bg-gray-800 rounded-lg shadow-lg p-4"><h3 class="text-lg font-semibold text-white mb-3">Category Rank Trends</h3><p class="text-gray-400">No completed weeks found to generate trend data.</p></div>';
                }

                let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                                <h3 class="text-lg font-semibold text-white mb-3">Category Rank Trends</h3>
                                <div class="overflow-x-auto">
                                    <table class="min-w-full divide-y divide-gray-700">
                                        <thead>
                                            <tr>
                                                <th class="table-header !text-left">Category</th>`;

                weeks.forEach(w => {
                    html += `<th class="table-header">W${w}</th>`;
                });

                html += `           </tr>
                                </thead>
                                <tbody class="bg-gray-900 divide-y divide-gray-700">`;

                categories.forEach(cat => {
                    html += `<tr><td class="table-cell !text-left font-semibold">${cat}</td>`;
                    weeks.forEach(w => {
                        const cellData = matrixData[cat] ? matrixData[cat][w] : [null, null];
                        const rank = cellData ? cellData[0] : null;
                        const delta = cellData ? cellData[1] : null;
                        html += `<td class="table-cell text-center">${formatRankDelta(rank, delta)}</td>`;
                    });
                    html += `</tr>`;
                });

                html += `       </tbody>
                            </table>
                        </div>
                    </div>`;
                return html;
            }

            /**
             * Creates the "Individual Week" trend table (List)
             */
             function createRankTrendListTable(listData) {
         let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                         <h3 class="text-lg font-semibold text-white mb-3">Category Rank Trends</h3>
                         <div class="overflow-x-auto">
                             <table class="min-w-full divide-y divide-gray-700">
                                 <thead>
                                     <tr>
                                         <th class="table-header !text-left">Category</th>
                                         <th class="table-header">Rank</th>
                                         <th class="table-header">Change</th>
                                     </tr>
                                 </thead>
                                 <tbody class="bg-gray-900 divide-y divide-gray-700">`;

         listData.forEach(row => {
             // Get the full formatted string, e.g., "4 <span>...</span>"
             const rankStr = formatRankDelta(row.rank, row.delta);

             // --- [START] FIX ---
             // Find the position of the delta span.
             const spanIndex = rankStr.indexOf('<span');
             let deltaStr;

             if (spanIndex !== -1) {
                 // If a span exists, extract it.
                 deltaStr = rankStr.substring(spanIndex);
             } else {
                 // Otherwise (e.g., rank is 4, delta is 0), default to (-)
                 deltaStr = '<span class="text-gray-500">(-)</span>';
             }
             // --- [END] FIX ---

             html += `<tr>
                         <td class="table-cell !text-left font-semibold">${row.category}</td>
                         <td class="table-cell text-center">${row.rank || '-'}</td>
                         <td class="table-cell text-center">${deltaStr}</td>
                     </tr>`;
         });

         html += `       </tbody>
                     </table>
                 </div>
             </div>`;
         return html;
     }



    // --- MODIFIED: Function to fetch and render transaction success ---
    async function fetchTransactionSuccess(teamName, week, viewMode) {
        loadingSpinner.classList.remove('hidden');
        historyContent.innerHTML = '';
        errorDiv.classList.add('hidden');

        try {
            const response = await fetch('/api/history/transaction_history', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // --- MODIFIED: Send the viewMode ---
                body: JSON.stringify({
                    team_name: teamName,
                    week: week,
                    view_mode: viewMode
                })
            });

            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            // --- NEW: Handle different view modes ---
            if (data.view_mode === 'team') {
                // --- TEAM VIEW LOGIC ---
                const addsTable = createTransactionTable('Player Adds', data.adds);
                const dropsTable = createTransactionTable('Player Drops', data.drops);

                let skaterStatsHtml = '';
                let goalieStatsHtml = '';

                if (data.is_weekly_view) {
                    skaterStatsHtml = createAddedPlayerStatsTable(
                        'Added Skater Contributions',
                        data.skater_stat_headers,
                        data.added_skater_stats
                    );
                    goalieStatsHtml = createAddedPlayerStatsTable(
                        'Added Goalie Contributions',
                        data.goalie_stat_headers,
                        data.added_goalie_stats
                    );
                }

                historyContent.innerHTML = `
                    <div class="flex flex-col lg:flex-row gap-6">
                        <div class="w-full lg:w-1/2 space-y-6">
                            ${addsTable}
                            ${skaterStatsHtml}
                            ${goalieStatsHtml}
                        </div>
                        <div class="w-full lg:w-1/2">
                            ${dropsTable}
                        </div>
                    </div>
                `;

            } else if (data.view_mode === 'league') {
                // --- LEAGUE VIEW LOGIC ---
                let leagueHtml = '';
                const teamNames = Object.keys(data.league_data).sort();

                if (teamNames.length === 0) {
                     leagueHtml = '<p class="text-gray-400">No transactions found for any team this week.</p>';
                }

                for (const teamName of teamNames) {
                    const teamData = data.league_data[teamName];
                    const skaterStatsHtml = createAddedPlayerStatsTable(
                        'Skaters',
                        data.skater_stat_headers,
                        teamData.skaters
                    );
                    const goalieStatsHtml = createAddedPlayerStatsTable(
                        'Goalies',
                        data.goalie_stat_headers,
                        teamData.goalies
                    );

                    leagueHtml += `
                        <div class="bg-gray-900 rounded-lg shadow-lg p-4 space-y-4">
                            <h2 class="text-xl font-semibold text-white">${teamName}</h2>
                            ${skaterStatsHtml}
                            ${goalieStatsHtml}
                        </div>
                    `;
                }

                // --- MODIFICATION: Replaced single-column layout with a 3-column grid ---
                // This will be 1 column on small, 2 on medium, and 3 on extra-large screens.
                historyContent.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">${leagueHtml}</div>`;
                // --- END MODIFICATION ---

            }
            // --- END NEW ---

        } catch (error) {
            console.error('Error fetching transaction data:', error);
            showError(error.message);
        } finally {
            loadingSpinner.classList.add('hidden');
        }
    }


    async function fetchCategoryStrengths(teamName, week) {
        loadingSpinner.classList.remove('hidden');
        historyContent.innerHTML = '';
        errorDiv.classList.add('hidden');

        try {
            const response = await fetch('/api/history/category_strengths', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ team_name: teamName, week: week })
            });

            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            // (This part is unchanged)
            addHeatmapData(data.skater_stats, data.team_headers);
            addHeatmapData(data.goalie_stats, data.team_headers);
            const skaterTable = createDynamicCategoryTable('Skater Stats', data.team_headers, data.skater_stats);
            const goalieTable = createDynamicCategoryTable('Goalie Stats', data.team_headers, data.goalie_stats);

            // --- [START] MODIFIED LOGIC for Trend Table & Styling ---
            let trendTableHtml = '';
            // Default to a full-width container
            let trendTableContainerOpen = '<div>';
            const trendTableContainerClose = '</div>';

            if (data.trend_data) {
                // Get all categories in the correct order
                const all_categories = data.skater_stats.map(s => s.category)
                    .concat(data.goalie_stats.map(g => g.category));

                if (data.trend_data.type === 'matrix') {
                    trendTableHtml = createRankTrendMatrixTable(all_categories, data.trend_data);
                } else if (data.trend_data.type === 'list') {
                    trendTableHtml = createRankTrendListTable(data.trend_data.data);

                    // --- STYLING FIX: Change the container for the list view ---
                    // This will be 50% width on large screens, max-width on smaller, and centered.
                    trendTableContainerOpen = '<div class="max-w-xl lg:max-w-none lg:w-1/2 mx-auto lg:mx-0">';
                }
            }
            // --- [END] MODIFIED LOGIC ---

            // Render tables stacked vertically, using the new container
            historyContent.innerHTML = `
                <div class="flex flex-col gap-6">
                    <div>
                        ${skaterTable}
                    </div>
                    <div>
                        ${goalieTable}
                    </div>

                    ${trendTableContainerOpen}
                        ${trendTableHtml}
                    ${trendTableContainerClose}
                </div>
            `;

        } catch (error) {
            console.error('Error fetching category strengths:', error);
            showError(error.message);
        } finally {
            loadingSpinner.classList.add('hidden');
        }
    }


    // --- MODIFIED: fetchAndRenderTable to pass view mode ---
    async function fetchAndRenderTable() {
            const selectedTeam = yourTeamSelect.value;
            const selectedWeek = weekSelect.value;
            const selectedReport = reportSelect.value;

            // --- MODIFIED: Pass currentViewMode to transaction report ---
            console.log(`Fetching data for: Team ${selectedTeam}, Week ${selectedWeek}, Report ${selectedReport}, View ${currentViewMode}`);

            // Route based on the selected report
            switch (selectedReport) {
                case 'bench_points':
                    await fetchBenchPoints(selectedTeam, selectedWeek);
                    break;

                case 'transaction_history':
                    await fetchTransactionSuccess(selectedTeam, selectedWeek, currentViewMode);
                    break;

              case 'category_strengths':
                  await fetchCategoryStrengths(selectedTeam, selectedWeek);
                  break;

                case 'tbd':
                    loadingSpinner.classList.remove('hidden');
                    historyContent.innerHTML = `<p class="text-gray-400">The "TBD" report is not yet implemented.</p>`;
                    loadingSpinner.classList.add('hidden');
                    break;

                case 'please_select':
                default:
                    loadingSpinner.classList.add('hidden');
                    historyContent.innerHTML = `<p class="text-gray-400">Please select a report to view.</p>`;
                    break;
            }
        }


    async function init() {
        loadingSpinner.classList.remove('hidden');
        const success = await fetchPageData();
        if (success) {
            populateDropdowns();
            setupEventListeners();
            await fetchAndRenderTable(); // Load initial data (will show "Please select")
            // Initially hide the toggle button until a report is selected
            handleReportChange();
        }
    }

    init();

})();
