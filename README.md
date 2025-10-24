yfpy Web Terminal

This is a web-based application that provides a secure, interactive terminal to execute queries against the Yahoo Fantasy Sports API using the yfpy Python library.

How It Works

The application uses a Flask backend with Socket.IO for real-time communication, and an Xterm.js frontend to create a functional terminal in your browser. It safely parses your commands to prevent security risks and pretty-prints the API output.

Deployment Instructions

This app is designed to be hosted on a service like Render. Authentication is handled via environment variables, so you never have to commit your secret keys to your repository.

Step 1: Get Yahoo API Credentials

Go to the Yahoo Developer Network: https://developer.yahoo.com/apps/

Click "Create an App".

Fill out the form:

Application Name: Give your app a name.

Application Type: Select "Installed App".

Description: Optional.

API Permissions: Select "Fantasy Sports" and make sure "Read/Write" is checked.

After creating the app, you will be given a Client ID (this is your Consumer Key) and a Client Secret (this is your Consumer Secret). Keep these safe.

Step 2: Run the Local Authentication Script

The Yahoo API uses OAuth2, which requires a one-time, browser-based login to grant your application access. You need to do this locally to get a refresh_token that the deployed web app can use.

Clone the repository to your local machine.

Create a virtual environment and install dependencies:

python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
pip install -r requirements.txt


Run the get_refresh_token.py script:

python get_refresh_token.py


Follow the prompts:

Enter the Consumer Key and Consumer Secret from Step 1.

Your web browser will open. Log in to your Yahoo account and grant the permissions.

After you approve, you will be redirected to a page that may show an error (this is normal). You can close the browser tab.

The script will print the three values you need for deployment. It will also save them in a private.json file, which you can discard after setting up your hosting.

Step 3: Deploy to Render

Push the code (including app.py, templates/, requirements.txt, etc.) to a GitHub repository.

Go to your Render dashboard and create a new "Web Service".

Connect your GitHub repository.

Configure the service:

Name: Give your service a name (e.g., yfpy-terminal).

Region: Choose a region.

Branch: main or your primary branch.

Runtime: Python 3.

Build Command: pip install -r requirements.txt

Start Command: gunicorn --worker-class eventlet -w 1 app:app

Go to the "Environment" tab and add the following Environment Variables:

YFPY_CONSUMER_KEY: Your Client ID from Step 1.

YFPY_CONSUMER_SECRET: Your Client Secret from Step 1.

YFPY_REFRESH_TOKEN: The refresh token you generated in Step 2.

PYTHON_VERSION: Set this to a recent Python version, like 3.11.5.

Click "Create Web Service". Render will build and deploy your application.

Step 4: Use the Terminal

Once deployed, visit your Render URL. You will see the terminal interface. You can now enter yfpy queries as if you were interacting with the data object.

Example Queries:

data.get_leagues_by_game_key('nhl')
data.get_league_metadata('YOUR_LEAGUE_ID')
data.get_team_metadata('YOUR_LEAGUE_ID.t.TEAM_ID')


You can also use the clear command to clear the terminal screen. Arrow keys can be used to navigate command history.