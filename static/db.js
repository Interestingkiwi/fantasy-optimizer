(async function() {
    const dbContent = document.getElementById('db-content');

    // This check is important because this script runs after being injected into home.html
    if (!dbContent) {
        return;
    }

    try {
        // This API endpoint does not exist, so we will show a message.
        // const response = await fetch('/api/db');
        // const data = await response.json();
        // if (data.error) {
        //     throw new Error(data.error);
        // }
        dbContent.innerHTML = '<p class="text-gray-400"></p>';

    } catch (error) {
        dbContent.innerHTML = `<p class="text-red-400">Error loading database content: ${error.message}</p>`;
    }
})();
