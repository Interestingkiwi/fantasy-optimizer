(async function() {
    const dbContent = document.getElementById('db-content');

    // This check is important because this script runs after being injected into home.html
    if (!dbContent) {
        return;
    }

    try {

        dbContent.innerHTML = '<p class="text-gray-400"></p>';

    } catch (error) {
        dbContent.innerHTML = `<p class="text-red-400">Error loading database content: ${error.message}</p>`;
    }
})();
