# Waste Management Reporting and Monitoring System

A Python-based website for reporting, monitoring and analysing community waste problems.

## Technology

- Python
- Built-in `http.server`
- SQLite
- HTML
- CSS
- JavaScript
- Matplotlib

No Flask, Django or Streamlit is used.

## Main Features

1. User registration and login
2. Password hashing
3. Waste report submission
4. Location, category, description and priority
5. Automatic date/time recording
6. Pending / In Progress / Resolved status
7. Search by location
8. Filter by status
9. Filter by priority
10. Edit reports
11. Delete reports
12. Analytics dashboard
13. Most-reported locations
14. Category and priority analysis
15. Matplotlib charts
16. CSV export
17. JSON export
18. JSON import
19. Activity logging
20. REST-style JSON endpoints
21. Command-line arguments
22. Exception handling

## Installation

Open PowerShell in this folder.

```powershell
pip install -r requirements.txt
```

## Create the database

```powershell
python database.py
```

## Start the website

```powershell
python main.py
```

Open:

http://localhost:8000

## Useful commands

Export CSV:

```powershell
python main.py --export-csv
```

Export JSON:

```powershell
python main.py --export-json
```

Run on another port:

```powershell
python main.py --port 8080
```

## API endpoints

Reports:

http://localhost:8000/api/reports

Statistics:

http://localhost:8000/api/statistics

## Project database

### users

Stores registered users.

### waste_reports

Stores waste reports and their status.

### activity_logs

Stores important user activities.

## Important presentation explanation

The frontend is built with HTML, CSS and JavaScript.

Python's built-in HTTP server receives browser requests and sends responses.

SQLite stores users and waste reports.

SQL queries are used for searching, filtering, counting and grouping data.

Matplotlib converts database statistics into visual charts.

The application does not require Flask.
