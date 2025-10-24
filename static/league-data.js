// Using setTimeout to ensure the DOM is ready after being dynamically loaded.
setTimeout(() => {
    const terminalInput = document.getElementById('terminal-input');
    const terminalOutput = document.getElementById('terminal-output');
    const terminalOutputContainer = document.getElementById('terminal-output-container');
    const submitButton = document.getElementById('terminal-submit-btn');

    if (!terminalInput || !terminalOutput || !terminalOutputContainer || !submitButton) {
        // Silently return if elements are not found.
        return;
    }

    const appendToTerminal = (text, type = 'output') => {
        const line = document.createElement('div');
        line.style.whiteSpace = 'pre-wrap'; // Ensure long lines wrap
        if (type === 'input') {
            line.innerHTML = `<span class="text-gray-500 mr-2">$</span>${text}`;
        } else if (type === 'error') {
            line.innerHTML = `<span class="text-red-400">${text}</span>`;
        } else {
            line.textContent = text;
        }
        terminalOutput.appendChild(line);
        terminalOutputContainer.scrollTop = terminalOutputContainer.scrollHeight;
    };

    const submitQuery = async () => {
        const query = terminalInput.value;
        if (!query) return;

        appendToTerminal(query, 'input');
        terminalInput.value = '';

        try {
            const response = await fetch('/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: query })
            });

            const data = await response.json();
            if (response.status === 401) {
                appendToTerminal(`Error: ${data.error}`, 'error');
                setTimeout(() => window.location.href = '/logout', 2000);
                return;
            }
            if (!response.ok) {
                throw new Error(data.error || 'An unknown error occurred.');
            }
            appendToTerminal(data.result);
        } catch (error) {
            appendToTerminal(`Error: ${error.message}`, 'error');
        }
    };

    const handleKeydown = (e) => {
        if (e.key === 'Enter') {
            submitQuery();
        }
    };

    // Attach listeners only once to prevent duplicates
    if (!terminalInput.dataset.listenerAttached) {
        terminalInput.addEventListener('keydown', handleKeydown);
        submitButton.addEventListener('click', submitQuery);
        terminalInput.dataset.listenerAttached = 'true';
    }
}, 0); // Delay of 0ms pushes this to the end of the execution queue
