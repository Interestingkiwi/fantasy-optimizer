H2H Fantasy Optimizer
This project is a web application designed to help users optimize their fantasy sports teams.

Project Structure
The project is organized into a client-server architecture.

.
├── client/              # Contains all front-end files
│   ├── index.html       # Main HTML file (the user interface)
│   ├── styles.css       # Custom CSS styles
│   └── script.js        # JavaScript for front-end logic
│
├── server/              # Contains all back-end files
│   └── app.py           # Python server (e.g., using Flask or FastAPI)
│
└── README.md            # This file


Client
The client directory holds all the files that will be sent to the user's web browser.

index.html: The main page structure.

styles.css: While we use Tailwind CSS for most styling, any custom or overriding styles can go here.

script.js: This file handles all user interactions, like button clicks and view changes.

Server
The server directory will hold your back-end logic.

app.py: This is where your Python code will live. It will handle tasks like the Yahoo OAuth authentication process, fetching data from the Yahoo API, and running your optimization algorithms. A basic Flask setup is included as a starting point.

Local Setup
Set up the Python Environment:

Navigate to the server directory.

It's recommended to use a virtual environment:

python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`


Install Flask:

pip install Flask


Run the Backend Server:

From the server directory, run:

flask run


This will start a development server, usually at http://127.0.0.1:5000.

View the Frontend:

Open the client/index.html file directly in your web browser. For development, you can use a simple tool like the "Live Server" extension in VS Code to serve the client-side files.