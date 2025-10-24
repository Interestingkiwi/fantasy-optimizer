(async function() {
    await new Promise(resolve => setTimeout(resolve, 0));

    const toggle = document.getElementById('use-test-db-toggle');
    const statusText = document.getElementById('test-db-status');

    if (!toggle || !statusText) {
        console.error('Settings page elements not found.');
        return;
    }

    // Fetch initial status
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        if (response.ok) {
            toggle.checked = data.use_test_db;
            if (!data.test_db_exists) {
                statusText.innerHTML += '<br><span class="text-red-400 font-bold">Warning: Test database file not found in /server directory. This toggle will not work.</span>';
                toggle.disabled = true;
            }
        } else {
            statusText.textContent = `Error fetching settings: ${data.error}`;
        }
    } catch (error) {
        statusText.textContent = `Error: ${error.message}`;
    }

    // Add event listener
    toggle.addEventListener('change', async () => {
        const use_test_db = toggle.checked;
        try {
            const response = await fetch('/api/settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ use_test_db: use_test_db })
            });
            const data = await response.json();
            if (!data.success) {
                throw new Error('Failed to update setting on server.');
            }
            console.log('Test DB mode updated to:', data.use_test_db);

            // Provide feedback to the user
            const originalStatus = statusText.innerHTML.split('<br>')[0];
            statusText.innerHTML = originalStatus + '<br><span class="text-green-400">Setting saved. Refresh other pages to see the effect.</span>';
            setTimeout(() => {
                statusText.innerHTML = originalStatus;
            }, 3000);

        } catch (error) {
            console.error('Error updating setting:', error);
            statusText.innerHTML += `<br><span class="text-red-400">Error saving setting: ${error.message}</span>`;
        }
    });
})();
