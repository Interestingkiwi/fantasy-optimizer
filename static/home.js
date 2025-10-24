document.addEventListener('DOMContentLoaded', () => {
    const logoutButton = document.getElementById('logout-button');
    const timestampText = document.getElementById('timestamp-text');
    const dropdownContainer = document.getElementById('dropdown-container');

    let pageData = null; // To store weeks, teams, etc.

    async function handleLogout() {
        // Redirect to logout endpoint, which will clear the session
        window.location.href = '/logout';
    }

    async function getTimestamp() {
        try {
            const response = await fetch('/api/db_timestamp');
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to fetch timestamp.');
            }

            if (data.timestamp) {
                timestampText.textContent = `League data was last pulled from Yahoo at ${data.timestamp}`;
            } else {
                timestampText.textContent = 'League data has not been updated yet. Please visit the League Database page.';
            }
        } catch (error) {
            console.error('Error setting timestamp:', error);
            timestampText.textContent = 'Error loading league data status.';
        }
    }

    async function initDropdowns() {
        try {
            const response = await fetch('/api/matchup_page_data');
            const data = await response.json();

            if (!response.ok || !data.db_exists) {
                // If DB doesn't exist, show a button to retry
                dropdownContainer.innerHTML = `<button id="reload-dropdowns" class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">Create DB then press to load</button>`;
                document.getElementById('reload-dropdowns').addEventListener('click', initDropdowns);
                return; // Stop further execution
            }

            // If DB exists, show and populate dropdowns with titles and side-by-side layout
            dropdownContainer.innerHTML = `
                <div class="flex items-center gap-2">
                    <label for="week-select" class="text-sm font-medium text-gray-300">Fantasy Week:</label>
                    <select id="week-select" class="bg-gray-700 border border-gray-600 text-white text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5">
                        <option selected>Choose a week</option>
                    </select>
                </div>
                <div class="flex items-center gap-2">
                    <label for="your-team-select" class="text-sm font-medium text-gray-300">Your Team:</label>
                    <select id="your-team-select" class="bg-gray-700 border border-gray-600 text-white text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5">
                        <option selected>Choose your team</option>
                    </select>
                </div>
            `;
            // Add the flex class back to the container itself
            dropdownContainer.classList.add('flex', 'items-center', 'gap-4');


            pageData = data;
            populateDropdowns();

            // Re-add event listeners after recreating the dropdowns
            document.getElementById('week-select').addEventListener('change', (e) => {
                localStorage.setItem('selectedWeek', e.target.value);
            });
            document.getElementById('your-team-select').addEventListener('change', (e) => {
                localStorage.setItem('selectedTeam', e.target.value);
            });

        } catch (error) {
            console.error('Initialization error for dropdowns:', error.message);
        }
    }

    function populateDropdowns() {
        const weekSelect = document.getElementById('week-select');
        const yourTeamSelect = document.getElementById('your-team-select');

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

        // Restore team selection from localStorage
        const savedTeam = localStorage.getItem('selectedTeam');
        if (savedTeam) {
            yourTeamSelect.value = savedTeam;
        }

        // Check if a session has started to handle the week selection
        if (!sessionStorage.getItem('fantasySessionStarted')) {
            // This is a new session. Default to the current week.
            const currentWeek = pageData.current_week;
            weekSelect.value = currentWeek;
            // Save it to localStorage so it persists during navigation
            localStorage.setItem('selectedWeek', currentWeek);
            // Mark the session as started
            sessionStorage.setItem('fantasySessionStarted', 'true');
        } else {
            // A session is active. Restore the last selected week from localStorage.
            const savedWeek = localStorage.getItem('selectedWeek');
            if (savedWeek) {
                weekSelect.value = savedWeek;
            } else {
                 // As a fallback, use the current week if nothing is in localStorage
                weekSelect.value = pageData.current_week;
            }
        }
    }

    if(logoutButton) {
        logoutButton.addEventListener('click', handleLogout);
    }

    if(timestampText) {
        getTimestamp();
    }

    // Initialize the dropdowns on page load
    initDropdowns();
});
