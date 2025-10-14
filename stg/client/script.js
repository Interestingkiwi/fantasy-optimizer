document.addEventListener('DOMContentLoaded', () => {
    // Get references to all necessary elements
    const loginView = document.getElementById('login-view');
    const appView = document.getElementById('app-view');
    const loginButton = document.getElementById('login-button');
    const logoutButton = document.getElementById('logout-button');
    const rememberMeCheckbox = document.getElementById('remember-me');

    // --- Function Definitions ---

    /**
     * Switches the view to the main application.
     */
    function showAppView() {
        loginView.classList.add('hidden');
        appView.classList.remove('hidden');
    }

    /**
     * Switches the view to the login page.
     */
    function showLoginView() {
        appView.classList.add('hidden');
        loginView.classList.remove('hidden');
    }

    /**
     * Simulates the login process.
     */
    function handleLogin() {
        // In a real application, this is where you would redirect to Yahoo's OAuth page.
        // For now, we'll simulate a successful login.

        if (rememberMeCheckbox.checked) {
            // If "Remember me" is checked, store the login state permanently.
            localStorage.setItem('isLoggedIn', 'true');
        }

        // Show the main application view.
        showAppView();
    }

    /**
     * Handles the logout process.
     */
    function handleLogout() {
        // Clear the stored login state.
        localStorage.removeItem('isLoggedIn');

        // Show the login page.
        showLoginView();
    }

    /**
     * Checks the stored login state when the page loads.
     * If the user chose to be remembered, they will bypass the login screen.
     */
    function checkInitialState() {
        if (localStorage.getItem('isLoggedIn') === 'true') {
            showAppView();
        } else {
            showLoginView();
        }
    }

    // --- Event Listeners ---

    // Add click listener for the login button.
    loginButton.addEventListener('click', handleLogin);

    // Add click listener for the logout button.
    logoutButton.addEventListener('click', handleLogout);

    // --- Initial Execution ---

    // Check the login state as soon as the page is ready.
    checkInitialState();
});
