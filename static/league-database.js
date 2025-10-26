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

    const handleDbAction = async () => {
        actionButton.disabled = true;
        actionButton.classList.add('opacity-50', 'cursor-not-allowed');
        actionButton.textContent = 'Processing...';

        // Clear previous logs and show a starting message
        logContainer.innerHTML = '<p class="text-yellow-400">Connecting to update stream...</p>';

        const captureLineups = captureLineupsCheckbox.checked;
        /*const skipStaticInfo = skipStaticInfoCheckbox.checked;
        const skipAvailablePlayers = skipAvailablePlayersCheckbox.checked;*/

        // --- Start the Update and Listen for Logs ---
        try {
            // 1. Start the update process on the server
            const response = await fetch('/api/update_db', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    capture_lineups: captureLineups/*,
                    skip_static_info: skipStaticInfo,
                    skip_available_players: skipAvailablePlayers*/
                })
            });

            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || 'Failed to start update process.');
            }

            // 2. Connect to the event stream to get live logs
            logContainer.innerHTML = '<p class="text-gray-400">Update process started. Waiting for logs...</p>';
            const eventSource = new EventSource('/stream');

            eventSource.onmessage = function(event) {
                // Clear the initial message on first real log
                if (logContainer.querySelector('p.text-gray-400')) {
                    logContainer.innerHTML = '';
                }

                const p = document.createElement('p');
                p.textContent = event.data;
                // Add color coding for different log levels
                if (event.data.startsWith('SUCCESS:')) {
                    p.className = 'text-green-400';
                } else if (event.data.startsWith('ERROR:')) {
                    p.className = 'text-red-400';
                } else {
                    p.className = 'text-gray-300';
                }
                logContainer.appendChild(p);
                logContainer.scrollTop = logContainer.scrollHeight; // Auto-scroll to the bottom
            };

            eventSource.onerror = function(err) {
                console.error('EventSource failed:', err);
                const p = document.createElement('p');
                p.className = 'text-red-500';
                p.textContent = 'Connection to log stream lost. Refreshing status...';
                logContainer.appendChild(p);
                eventSource.close();
                // Refresh the main status when the stream closes
                fetchStatus();
            };

        } catch (error) {
            console.error('Error performing DB action:', error);
            logContainer.innerHTML = `<p class="text-red-400">Error: ${error.message}</p>`;
            // Re-enable the button on failure to start
            actionButton.disabled = false;
            actionButton.classList.remove('opacity-50', 'cursor-not-allowed');
            actionButton.textContent = 'Update Failed';
        }
    };

    actionButton.addEventListener('click', handleDbAction);

    // Initial load
    fetchStatus();

})();
