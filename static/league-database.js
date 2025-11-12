// This script will manage the league-database.html page
(async function() {
    // A short delay to ensure the page elements are in the DOM
    await new Promise(resolve => setTimeout(resolve, 0));

    const statusText = document.getElementById('db-status-text');
    const actionButton = document.getElementById('db-action-button');
    const captureLineupsCheckbox = document.getElementById('capture-daily-lineups');
/*    const skipStaticInfoCheckbox = document.getElementById('skip-static-info');
    const skipAvailablePlayersCheckbox = document.getElementById('skip-available-players'); */
    const logContainer = document.getElementById('log-container'); // Get the new log container

    if (!statusText || !actionButton || !captureLineupsCheckbox || /*!skipStaticInfoCheckbox || !skipAvailablePlayersCheckbox ||*/ !logContainer) {
        console.error('Database page elements not found.');
        return;
    }

    const updateStatus = (data) => {
        if (data.is_test_db) {
            statusText.innerHTML = `<strong>TEST MODE ACTIVE.</strong> All pages are reading from <span class="font-mono text-green-400">${data.league_name}</span>. <br>You can still use the button below to build or update a separate, live database.`;
            actionButton.textContent = 'Build/Update Live Database';
            return;
        }

        if (data.db_exists) {
            const date = new Date(data.timestamp * 1000);
            statusText.textContent = `Your league: '${data.league_name}'s data is up to date as of: ${date.toLocaleString()}`;
            actionButton.textContent = 'Update Database';
        } else {
            statusText.textContent = "Your league's data has not been initialized. Please initialize the database.";
            actionButton.textContent = 'Initialize Database';
        }
    };

    const fetchStatus = async () => {
        try {
            const response = await fetch('/api/db_status');
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Failed to fetch status');
            updateStatus(data);
        } catch (error) {
            console.error('Error fetching DB status:', error);
            statusText.textContent = `Could not determine database status. ${error.message}`;
            actionButton.textContent = 'Error';
        } finally {
            actionButton.disabled = false;
            actionButton.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    };

    let eventSource = null;

    const connectToLogStream = (buildId) => {
        // Close any existing stream
        if (eventSource) {
            eventSource.close();
        }

        actionButton.textContent = 'Update in Progress...';

        eventSource = new EventSource(`/api/db_log_stream?build_id=${buildId}`);

        eventSource.onmessage = function(event) {

            // --- MODIFICATION: Handle Invalid Build ID error first ---
            if (event.data.startsWith('ERROR: Invalid build ID') || event.data.startsWith('ERROR: No build_id')) {
                logContainer.innerHTML = `
                    <p class="text-yellow-400 font-bold">The Database Update is in fact in progress, only you are unable to see the log.</p>
                    <p class="text-gray-300 mt-2">This can happen if the build was started from another device or a previous session, and that build has just completed.</p>
                    <p class="text-gray-300">Please wait a few minutes, and refresh the website to see if the update has been complete.</p>
                    <p class="text-gray-300">Please do not start an additional update, thank you.</p>
                `;
                logContainer.scrollTop = logContainer.scrollHeight; // Auto-scroll

                // Manually stop the stream and reset the button
                eventSource.close();
                eventSource = null;
                actionButton.disabled = false;
                actionButton.classList.remove('opacity-50', 'cursor-not-allowed');
                actionButton.textContent = 'Refresh Status';
                fetchStatus();
                return;
            }
            // --- END MODIFICATION ---

            // 3. Check for the sentinel message
            if (event.data === '__DONE__') {
                eventSource.close();
                eventSource = null;
                logContainer.scrollTop = logContainer.scrollHeight;
                // Re-enable button and refresh status
                actionButton.disabled = false;
                actionButton.classList.remove('opacity-50', 'cursor-not-allowed');
                actionButton.textContent = 'Update Complete';
                fetchStatus(); // Refresh main status
                return;
            }

            const p = document.createElement('p');
            p.textContent = event.data;

            if (event.data.startsWith('--- SUCCESS:')) {
                p.className = 'text-green-400 font-bold';
            } else if (event.data.startsWith('--- ERROR:') || event.data.startsWith('--- FATAL ERROR:')) {
                p.className = 'text-red-400 font-bold';
            } else if (event.data.startsWith('ERROR:')) {
                p.className = 'text-red-400';
            } else if (event.data.startsWith('---')) {
                 p.className = 'text-yellow-400';
            } else {
                p.className = 'text-gray-300';
            }
            logContainer.appendChild(p);
            logContainer.scrollTop = logContainer.scrollHeight; // Auto-scroll
        };

        eventSource.onerror = function(err) {
            console.error('EventSource failed:', err);
            const p = document.createElement('p');
            p.className = 'text-red-500';
            p.textContent = 'Connection to log stream lost. Refreshing status...';
            logContainer.appendChild(p);
            if (eventSource) eventSource.close();
            eventSource = null;
            // Refresh the main status when the stream closes
            fetchStatus();
            // Re-enable button
            actionButton.disabled = false;
            actionButton.classList.remove('opacity-50', 'cursor-not-allowed');
            actionButton.textContent = 'Stream Error';
        };
    };
    // --- END NEW FUNCTION ---

    const handleDbAction = async (event) => {
        event.preventDefault();
        actionButton.disabled = true;
        actionButton.classList.add('opacity-50', 'cursor-not-allowed');
        actionButton.textContent = 'Starting Update...';
        logContainer.innerHTML = ''; // Clear previous logs

        // Close any existing stream
        if (eventSource) {
            eventSource.close();
        }

        try {
            const options = {
                'capture_lineups': captureLineupsCheckbox.checked,
                // These are commented out in your HTML, but get them if they exist
                'skip_static': document.getElementById('skip-static-info')?.checked || false,
                'skip_players': document.getElementById('skip-available-players')?.checked || false,
            };

            // 1. Call the action endpoint
            const response = await fetch('/api/db_action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(options)
            });

            if (!response.ok) {
                const err = await response.json();

                // --- MODIFICATION: Handle 409 "in progress" error ---
                if (response.status === 409 && err.build_id) {
                    // This is THE FIX: We got the active build_id, so connect to it.
                    logContainer.innerHTML = '<p class="text-yellow-400">A build is already in progress. Attempting to connect to the log stream...</p>';
                    connectToLogStream(err.build_id);
                } else if (response.status === 409) {
                    // Build is in progress, but we couldn't get the build_id.
                    // This will trigger the catch block with the backup message.
                    throw new Error('A build is already in progress.');
                } else {
                    // A different, unexpected error
                    throw new Error(err.error || `Server error: ${response.status}`);
                }
                // --- END MODIFICATION ---

            } else {
                // This is the normal 200 OK response
                const data = await response.json();
                if (!data.success || !data.build_id) {
                     throw new Error('Failed to start build process. Server did not return a build_id.');
                }
                // --- MODIFICATION: Use the new function ---
                connectToLogStream(data.build_id);
                // --- END MODIFICATION ---
            }

        } catch (error) {
            console.error('Error performing DB action:', error);

            // --- MODIFICATION: Add your custom backup message here ---
            let errorMsg = error.message || 'An unknown error occurred.';
            if (errorMsg.includes('A build is already in progress.')) {
                logContainer.innerHTML = `
                    <p class="text-yellow-400 font-bold">The Database Update is in fact in progress, only you are unable to see the log.</p>
                    <p class="text-gray-300 mt-2">This can happen if the build was started from another device or session.</p>
                    <p class="text-gray-300">Please wait a few minutes, and refresh the website to see if the update has been complete.</p>
                    <p class="text-gray-300">Please do not start an additional update, thank you.</p>
                `;
                // Keep the button disabled, but update text
                actionButton.textContent = 'Build in Progress';
            } else {
                // A different error occurred
                logContainer.innerHTML = `<p class="text-red-400">Error: ${errorMsg}</p>`;
                // Re-enable the button on other failures
                actionButton.disabled = false;
                actionButton.classList.remove('opacity-50', 'cursor-not-allowed');
                actionButton.textContent = 'Update Failed';
            }
            // --- END MODIFICATION ---
        }
    };

    actionButton.addEventListener('click', handleDbAction);

    // Initial load
    fetchStatus();

})();
