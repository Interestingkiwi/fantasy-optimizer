(async function() {
    // Wait for the DOM to be fully loaded before running
    await new Promise(resolve => {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", resolve);
        } else {
            resolve();
        }
    });

    // --- Element IDs (unchanged) ---
    const errorDiv = document.getElementById('schedule-error-message');
    const weekSelect = document.getElementById('schedule-week-select');
    const reportSelect = document.getElementById('schedule-report-select');
    const scheduleContent = document.getElementById('schedule-content');
    const loadingSpinner = document.getElementById('loading-spinner-schedules');

    let pageData = null;

    function showError(message) {
        errorDiv.textContent = message;
        errorDiv.classList.remove('hidden');
        scheduleContent.innerHTML = '';
        loadingSpinner.classList.add('hidden');
    }

    async function fetchPageData() {
        try {
            const response = await fetch('/api/schedules_page_data');
            if (!response.ok) {
                throw new Error(`Failed to load page data. Server responded with ${response.status}`);
            }
            const data = await response.json();
            if (!data.db_exists) {
                showError(data.error || "Database not found. Please create one on the 'League Database' page.");
                return false;
            }
            pageData = data;
            return true;
        } catch (error) {
            console.error('Error fetching page data:', error);
            showError(`Error fetching page data: ${error.message}`);
            return false;
        }
    }

    function populateDropdowns() {
        // --- Week Dropdown (unchanged) ---
        const allWeeks = pageData.weeks;
        let weekOptions = '<option value="all">All Season</option>';
        weekOptions += allWeeks.map(week =>
            `<option value="${week.week_num}">
                Week ${week.week_num} (${week.start_date} to ${week.end_date})
            </option>`
        ).join('');
        weekSelect.innerHTML = weekOptions;
        weekSelect.value = "all";

        // --- Report Dropdown ---
        // --- MODIFIED: Added "Off Days" ---
        let reportOptions = '';
        reportOptions += '<option value="please_select">--Please Select--</option>';
        reportOptions += '<option value="off_days">Off Days</option>';
        reportOptions += '<option value="playoff_schedules">Playoff Schedules</option>';
        reportOptions += '<option value="tbd">TBD</option>';
        reportSelect.innerHTML = reportOptions;
        // --- END MODIFIED ---
    }

    function setupEventListeners() {
        weekSelect.addEventListener('change', fetchAndRenderReport);
        reportSelect.addEventListener('change', fetchAndRenderReport);
        // --- NEW: Add sort listener ---
        scheduleContent.addEventListener('click', handleTableSort);
    }

    // --- [START] NEW: Table Sorting Logic (from season-history.js) ---
    function handleTableSort(event) {
        const header = event.target.closest('.sortable-header');
        if (!header) return;

        const table = header.closest('table');
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const sortKey = header.dataset.sortKey;

        let currentDir = header.dataset.sortDir || 'none';
        let nextDir = (currentDir === 'asc') ? 'desc' : 'asc';

        table.querySelectorAll('.sortable-header').forEach(th => {
            th.dataset.sortDir = 'none';
            const arrow = th.querySelector('.sort-arrow');
            if (arrow) arrow.remove();
        });

        header.dataset.sortDir = nextDir;
        const arrowSpan = document.createElement('span');
        arrowSpan.className = 'sort-arrow ml-1';
        arrowSpan.textContent = (nextDir === 'asc') ? '▲' : '▼';
        header.appendChild(arrowSpan);

        const headers = Array.from(header.parentElement.children);
        const colIndex = headers.indexOf(header);

        rows.sort((rowA, rowB) => {
            const cellA = rowA.children[colIndex];
            const cellB = rowB.children[colIndex];
            let valA, valB;

            if (sortKey === 'team') {
                valA = cellA.textContent.toLowerCase();
                valB = cellB.textContent.toLowerCase();
            } else {
                valA = parseFloat(cellA.textContent) || 0;
                valB = parseFloat(cellB.textContent) || 0;
            }

            let sortVal = 0;
            if (typeof valA === 'string') {
                sortVal = valA.localeCompare(valB);
            } else {
                sortVal = valA - valB;
            }

            if (nextDir === 'desc') {
                sortVal *= -1;
            }
            return sortVal;
        });

        rows.forEach(row => tbody.appendChild(row));
    }
    // --- [END] NEW: Table Sorting Logic ---


    // --- [START] NEW: Table Creation Helpers ---

    /**
     * Creates the HTML table for the single week "Off Days" report.
     */
     function createSingleWeekOffDaysTable(rows) {
         let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                         <div class="overflow-x-auto">
                             <table class="min-w-full divide-y divide-gray-700">
                                 <thead>
                                     <tr>
                                         <th class="table-header !text-left sortable-header cursor-pointer" data-sort-key="team">Team</th>
                                         <th class="table-header sortable-header cursor-pointer" data-sort-key="off_days">Off Days This Week</th>
                                         <th class="table-header sortable-header cursor-pointer" data-sort-key="total_games">Total Games</th>
                                         <th class="table-header !text-left sortable-header cursor-pointer" data-sort-key="opponents">Opponents</th>
                                         <th class="table-header sortable-header cursor-pointer" data-sort-key="opponent_avg_ga">Opponent Avg GA</th>
                                         <th class="table-header sortable-header cursor-pointer" data-sort-key="opponent_avg_pt_pct">Opponent Avg Pt %</th>
                                         </tr>
                                 </thead>
                                 <tbody class="bg-gray-900 divide-y divide-gray-700">`;

         for (const row of rows) {
             html += `<tr>
                         <td class="table-cell !text-left">${row.team}</td>
                         <td class="table-cell text-center">${row.off_days}</td>
                         <td class="table-cell text-center">${row.total_games}</td>
                         <td class="table-cell !text-left">${row.opponents || ''}</td>
                         <td class="table-cell text-center text-gray-500">${row.opponent_avg_ga}</td>
                         <td class="table-cell text-center text-gray-500">${row.opponent_avg_pt_pct}</td>
                         </tr>`;
         }

         html += `           </tbody>
                         </table>
                     </div>
                 </div>`;
         return html;
     }
    /**
     * Creates the HTML table for the "All Season" (Past or ROS) "Off Days" report.
     */
    function createMultiWeekOffDaysTable(title, data) {
        const { headers, rows } = data;

        let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                        <h3 class="text-lg font-semibold text-white mb-3">${title}</h3>
                        <div class="overflow-x-auto">
                            <table class="min-w-full divide-y divide-gray-700">
                                <thead>
                                    <tr>
                                        <th class="table-header !text-left sortable-header cursor-pointer" data-sort-key="team">Team</th>`;

        for (const header of headers) {
            // Use week number (e.g., "Week 6") as the sort key
            html += `<th class="table-header sortable-header cursor-pointer" data-sort-key="${header}">${header}</th>`;
        }
        if (title === "Off Days For ROS") {
                html += `<th class="table-header sortable-header cursor-pointer" data-sort-key="Total">Total</th>`;
            }
        html += `           </tr>
                        </thead>
                        <tbody class="bg-gray-900 divide-y divide-gray-700">`;

        for (const row of rows) {
            html += `<tr>
                        <td class="table-cell !text-left">${row.team}</td>`;
            for (const header of headers) {
                html += `<td class="table-cell text-center">${row[header] || 0}</td>`;
            }
            if (title === "Off Days For ROS") {
                        // Making this bold to stand out
                        html += `<td class="table-cell text-center font-bold">${row['Total'] || 0}</td>`;
                    }
            html += `</tr>`;
        }

        html += `           </tbody>
                        </table>
                    </div>
                </div>`;
        return html;
    }


    function createPlayoffScheduleTable(data) {
            const { title, headers, rows } = data;

            // --- NEW: Define the divider class we'll use ---
            const dividerClass = 'border-r-2 border-gray-600';

            let html = `<div class="bg-gray-800 rounded-lg shadow-lg p-4">
                            <h3 class="text-lg font-semibold text-white mb-3">${title}</h3>
                            <div class="overflow-x-auto">
                                <table class="min-w-full divide-y divide-gray-700">
                                    <thead>
                                        <tr>`;

            // Create headers dynamically
            for (const header of headers) {
                let sortKey = header.toLowerCase().replace(/ /g, '_');
                let helpText = '';
                if (header.includes(" Games")) {
                    helpText = `<span class="help-icon ml-1" data-title="Games (Off Days)" data-text="Total games played in the week, with (off-day games) in parentheses.">?</span>`;
                }
                if (header === 'Team') sortKey = 'team';

                // --- MODIFIED: Add base class and conditional divider class ---
                let thClass = 'table-header sortable-header cursor-pointer';
                if (header === 'Team' || header.includes('Opponent Avg Pt %')) {
                    thClass += ` ${dividerClass}`; // NEW
                }

                html += `<th class="${thClass}" data-sort-key="${sortKey}">
                            <div class="flex items-center justify-center">
                                ${header}
                                ${helpText}
                            </div>
                         </th>`;
            }

            html += `           </tr>
                            </thead>
                            <tbody class="bg-gray-900 divide-y divide-gray-700">`;

            // Create rows
            for (const row of rows) {
                html += `<tr>`;
                for (const header of headers) {
                    let content = row[header] || '';
                    let cellClass = 'table-cell text-center'; // Base class

                    // Left-align team name and Opponents
                    if (header === 'Team' || header.includes('Opponents')) {
                        cellClass = 'table-cell !text-left';
                    }
                    // Center N/A values
                    if (content === 'N/A') {
                        cellClass = 'table-cell text-center text-gray-500';
                    }

                    // --- MODIFIED: Add conditional divider class ---
                    if (header === 'Team' || header.includes('Opponent Avg Pt %')) {
                        cellClass += ` ${dividerClass}`; // NEW
                    }

                    html += `<td class="${cellClass}">${content}</td>`;
                }
                html += `</tr>`;
            }

            html += `           </tbody>
                            </table>
                        </div>
                    </div>`;
            return html;

        }
    // --- [END] NEW: Table Creation Helpers ---


    // --- [START] NEW: Off Days Fetch Function ---
    /**
     * Fetches data for the "Off Days" report from the backend.
     */
    async function fetchOffDaysReport(week) {
        loadingSpinner.classList.remove('hidden');
        scheduleContent.innerHTML = '';
        errorDiv.classList.add('hidden');

        try {
            const response = await fetch('/api/schedules/off_days', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ week: week })
            });

            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            if (data.report_type === 'single_week') {
                scheduleContent.innerHTML = createSingleWeekOffDaysTable(data.table_data);
            } else if (data.report_type === 'all_season') {
                const rosTable = createMultiWeekOffDaysTable("Off Days For ROS", data.ros_data);
                const pastTable = createMultiWeekOffDaysTable("Off Days From Past Weeks", data.past_data);
                scheduleContent.innerHTML = `
                    <div class="space-y-6">
                        ${rosTable}
                        ${pastTable}
                    </div>
                `;
            }

        } catch (error) {
            console.error('Error fetching off days report:', error);
            showError(error.message);
        } finally {
            loadingSpinner.classList.add('hidden');
        }
    }
    // --- [END] NEW: Off Days Fetch Function ---

    async function fetchPlayoffSchedules() {
            loadingSpinner.classList.remove('hidden');
            scheduleContent.innerHTML = '';
            errorDiv.classList.add('hidden');

            try {
                // This endpoint doesn't need any POST data (like week)
                const response = await fetch('/api/schedules/playoff_schedules', {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' }
                });

                if (!response.ok) throw new Error(`Server error: ${response.status}`);
                const data = await response.json();
                if (data.error) throw new Error(data.error);

                if (data.rows.length === 0) {
                     showError("Could not determine playoff weeks. Please check your league settings and database.");
                     return;
                }

                // Render the single, dynamic table
                scheduleContent.innerHTML = createPlayoffScheduleTable(data);

            } catch (error) {
                console.error('Error fetching playoff schedules report:', error);
                showError(error.message);
            } finally {
                loadingSpinner.classList.add('hidden');
            }
        }
        // --- [END] NEW: Playoff Schedules Fetch Function ---


        async function fetchAndRenderReport() {
            const selectedWeek = weekSelect.value;
            const selectedReport = reportSelect.value;

            console.log(`Fetching data for: Week ${selectedWeek}, Report ${selectedReport}`);

            loadingSpinner.classList.remove('hidden');

            // --- MODIFIED: Added "playoff_schedules" case ---
            switch (selectedReport) {
                case 'off_days':
                    await fetchOffDaysReport(selectedWeek);
                    break;

                case 'playoff_schedules': // NEW
                    await fetchPlayoffSchedules(); // This function ignores selectedWeek
                    break;

                case 'tbd':
                    scheduleContent.innerHTML = `<p class="text-gray-400">The "TBD" report is not yet implemented.</p>`;
                    loadingSpinner.classList.add('hidden');
                    break;

                case 'please_select':
                default:
                    scheduleContent.innerHTML = `<p class="text-gray-400">Please select a report to view.</p>`;
                    loadingSpinner.classList.add('hidden');
                    break;
            }
            // --- END MODIFIED ---
        }

    async function init() {
        loadingSpinner.classList.remove('hidden');
        const success = await fetchPageData();
        if (success) {
            populateDropdowns();
            setupEventListeners();
            await fetchAndRenderReport();
        }
    }

    init();

})();
