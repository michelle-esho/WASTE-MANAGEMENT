import argparse
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import sqlite3
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from database import create_database, get_connection

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
CHART_DIR = "charts"
LOG_FILE = "waste_management.log"

sessions = {}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_activity(user_id, action, details=""):
    try:
        connection = get_connection()
        connection.execute(
            """
            INSERT INTO activity_logs (user_id, action, details, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, action, details, now())
        )
        connection.commit()
        connection.close()
    except Exception as error:
        logging.exception("Could not save activity log: %s", error)


def hash_password(password):
    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()
    return salt + ":" + password_hash


def verify_password(password, stored_password):
    if ":" not in stored_password:
        return hmac.compare_digest(password, stored_password)

    salt, stored_hash = stored_password.split(":", 1)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()

    return hmac.compare_digest(password_hash, stored_hash)


def escape_html(value):
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )


def load_template(filename):
    with open(
        os.path.join("templates", filename),
        "r",
        encoding="utf-8"
    ) as file:
        return file.read()


def render_message(title, message, link="/", link_text="Back"):
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{escape_html(title)}</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <header>
            <div class="logo">♻️ Waste Management</div>
            <nav>
                <a href="/">Home</a>
                <a href="/report">Report Waste</a>
                <a href="/reports">Reports</a>
                <a href="/analytics">Analytics</a>
            </nav>
        </header>
        <main class="message-page">
            <div class="message-card">
                <h1>{escape_html(title)}</h1>
                <p>{escape_html(message)}</p>
                <a class="primary-button" href="{escape_html(link)}">{escape_html(link_text)}</a>
            </div>
        </main>
    </body>
    </html>
    """


def get_logged_in_user(handler):
    cookie = handler.headers.get("Cookie", "")
    session_id = None

    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("session_id="):
            session_id = part.split("=", 1)[1]
            break

    if not session_id:
        return None

    user_id = sessions.get(session_id)
    if not user_id:
        return None

    connection = get_connection()
    user = connection.execute(
        """
        SELECT id, full_name, email
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()
    connection.close()
    return user


def redirect(handler, location):
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.end_headers()


def send_html(handler, html, status=200):
    data = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def send_json(handler, payload, status=200):
    data = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def send_file(handler, filepath, content_type):
    with open(filepath, "rb") as file:
        data = file.read()

    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def parse_form(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length).decode("utf-8")
    parsed = parse_qs(body)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def get_query(parsed_url):
    query = parse_qs(parsed_url.query)
    return {
        key: values[0] if values else ""
        for key, values in query.items()
    }


def create_charts():
    os.makedirs(CHART_DIR, exist_ok=True)

    if not MATPLOTLIB_AVAILABLE:
        return

    connection = get_connection()

    status_rows = connection.execute("""
        SELECT status, COUNT(*) AS total
        FROM waste_reports
        GROUP BY status
        ORDER BY total DESC
    """).fetchall()

    priority_rows = connection.execute("""
        SELECT priority, COUNT(*) AS total
        FROM waste_reports
        GROUP BY priority
        ORDER BY total DESC
    """).fetchall()

    category_rows = connection.execute("""
        SELECT category, COUNT(*) AS total
        FROM waste_reports
        GROUP BY category
        ORDER BY total DESC
    """).fetchall()

    location_rows = connection.execute("""
        SELECT location, COUNT(*) AS total
        FROM waste_reports
        GROUP BY location
        ORDER BY total DESC
        LIMIT 10
    """).fetchall()

    connection.close()

    chart_data = [
        ("status_chart.png", "Reports by Status", status_rows),
        ("priority_chart.png", "Reports by Priority", priority_rows),
        ("category_chart.png", "Reports by Waste Category", category_rows),
        ("location_chart.png", "Top Reported Locations", location_rows),
    ]

    for filename, title, rows in chart_data:
        path = os.path.join(CHART_DIR, filename)

        labels = [row[0] for row in rows]
        values = [row[1] for row in rows]

        plt.figure(figsize=(8, 5))

        if labels:
            plt.bar(labels, values)
            plt.title(title)
            plt.xlabel("Group")
            plt.ylabel("Number of Reports")
            plt.xticks(rotation=25, ha="right")
            plt.tight_layout()
        else:
            plt.text(0.5, 0.5, "No data available", ha="center", va="center")
            plt.axis("off")

        plt.savefig(path, dpi=120)
        plt.close()


class WasteManagementHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = get_query(parsed_url)

        if path == "/static/" or path.startswith("/static/"):
            return super().do_GET()

        if path == "/charts/" or path.startswith("/charts/"):
            filename = os.path.basename(path)
            filepath = os.path.join(CHART_DIR, filename)
            if os.path.isfile(filepath):
                return send_file(self, filepath, "image/png")
            return send_html(self, "Chart not found", 404)

        if path == "/api/reports":
            return self.api_reports()

        if path == "/api/statistics":
            return self.api_statistics()

        if path == "/":
            html = load_template("index.html")
            user = get_logged_in_user(self)

            if user:
                welcome = f"""
                <div class="welcome-message">
                    <h2>Welcome back, {escape_html(user["full_name"])}!</h2>
                    <p>Monitor waste reports and help keep communities clean.</p>
                </div>
                """
            else:
                welcome = """
                <div class="welcome-message">
                    <h2>Welcome to the Waste Management System</h2>
                    <p>Create an account or log in to report and manage waste problems.</p>
                </div>
                """

            connection = get_connection()
            total = connection.execute(
                "SELECT COUNT(*) AS total FROM waste_reports"
            ).fetchone()["total"]
            pending = connection.execute(
                "SELECT COUNT(*) AS total FROM waste_reports WHERE status = 'Pending'"
            ).fetchone()["total"]
            resolved = connection.execute(
                "SELECT COUNT(*) AS total FROM waste_reports WHERE status = 'Resolved'"
            ).fetchone()["total"]
            connection.close()

            html = html.replace("{{WELCOME_MESSAGE}}", welcome)
            html = html.replace("{{TOTAL_REPORTS}}", str(total))
            html = html.replace("{{PENDING_REPORTS}}", str(pending))
            html = html.replace("{{RESOLVED_REPORTS}}", str(resolved))

            return send_html(self, html)

        if path == "/register":
            return send_html(self, load_template("register.html"))

        if path == "/login":
            return send_html(self, load_template("login.html"))

        if path == "/forgot-password":
            return send_html(self, load_template("forgot_password.html"))

        if path == "/report":
            if not get_logged_in_user(self):
                return redirect(self, "/login")
            return send_html(self, load_template("report.html"))

        if path == "/reports":
            return self.reports_page(query)

        if path == "/analytics":
            return self.analytics_page()

        if path == "/edit-report":
            return self.edit_report_page(query)

        if path == "/logout":
            cookie = self.headers.get("Cookie", "")
            session_id = None

            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith("session_id="):
                    session_id = part.split("=", 1)[1]
                    break

            if session_id:
                sessions.pop(session_id, None)

            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                "session_id=; Max-Age=0; Path=/; HttpOnly"
            )
            self.end_headers()
            return

        return send_html(self, render_message(
            "404 - Page Not Found",
            "The page you requested does not exist.",
            "/",
            "Go Home"
        ), 404)

    def reports_page(self, query):
        user = get_logged_in_user(self)
        if not user:
            return redirect(self, "/login")

        location = query.get("location", "").strip()
        status = query.get("status", "").strip()
        priority = query.get("priority", "").strip()

        connection = get_connection()

        sql = """
            SELECT id, location, category, description,
                   priority, status, reported_at, updated_at
            FROM waste_reports
            WHERE user_id = ?
        """
        parameters = [user["id"]]

        if location:
            sql += " AND location LIKE ?"
            parameters.append("%" + location + "%")

        if status in ("Pending", "In Progress", "Resolved"):
            sql += " AND status = ?"
            parameters.append(status)

        if priority in ("Low", "Medium", "High"):
            sql += " AND priority = ?"
            parameters.append(priority)

        sql += " ORDER BY id DESC"

        reports = connection.execute(sql, parameters).fetchall()
        connection.close()

        report_html = ""

        for report in reports:
            report_html += f"""
            <article class="report-card">
                <div class="report-card-header">
                    <h3>{escape_html(report["category"])}</h3>
                    <span class="status-badge {report["status"].lower().replace(" ", "-")}">
                        {escape_html(report["status"])}
                    </span>
                </div>

                <p><strong>Location:</strong> {escape_html(report["location"])}</p>
                <p><strong>Description:</strong> {escape_html(report["description"])}</p>
                <p><strong>Priority:</strong> {escape_html(report["priority"])}</p>
                <p><strong>Reported:</strong> {escape_html(report["reported_at"])}</p>

                <div class="report-actions">
                    <a class="small-button" href="/edit-report?id={report["id"]}">
                        Edit
                    </a>

                    <form method="POST" action="/update-status">
                        <input type="hidden" name="report_id" value="{report["id"]}">
                        <select name="status">
                            <option value="Pending" {"selected" if report["status"] == "Pending" else ""}>Pending</option>
                            <option value="In Progress" {"selected" if report["status"] == "In Progress" else ""}>In Progress</option>
                            <option value="Resolved" {"selected" if report["status"] == "Resolved" else ""}>Resolved</option>
                        </select>
                        <button class="small-button" type="submit">Update Status</button>
                    </form>

                    <form method="POST" action="/delete-report"
                          onsubmit="return confirm('Delete this report?');">
                        <input type="hidden" name="report_id" value="{report["id"]}">
                        <button class="danger-button" type="submit">Delete</button>
                    </form>
                </div>
            </article>
            """

        if not report_html:
            report_html = """
            <div class="no-reports">
                <h3>No reports found</h3>
                <p>Try another search or create a new waste report.</p>
            </div>
            """

        statuses = ["Pending", "In Progress", "Resolved"]
        priorities = ["Low", "Medium", "High"]

        status_options = "".join(
            f'<option value="{s}" {"selected" if status == s else ""}>{s}</option>'
            for s in statuses
        )

        priority_options = "".join(
            f'<option value="{p}" {"selected" if priority == p else ""}>{p}</option>'
            for p in priorities
        )

        html = load_template("reports.html")
        html = html.replace("{{REPORTS}}", report_html)
        html = html.replace("{{SEARCH_LOCATION}}", escape_html(location))
        html = html.replace("{{STATUS_FILTER_OPTIONS}}", status_options)
        html = html.replace("{{PRIORITY_FILTER_OPTIONS}}", priority_options)

        return send_html(self, html)

    def edit_report_page(self, query):
        user = get_logged_in_user(self)
        if not user:
            return redirect(self, "/login")

        report_id = query.get("id", "")
        if not report_id.isdigit():
            return redirect(self, "/reports")

        connection = get_connection()
        report = connection.execute(
            """
            SELECT *
            FROM waste_reports
            WHERE id = ? AND user_id = ?
            """,
            (int(report_id), user["id"])
        ).fetchone()
        connection.close()

        if not report:
            return redirect(self, "/reports")

        categories = [
            "Plastic Waste",
            "Food Waste",
            "Illegal Dumping",
            "Blocked Drainage",
            "Food/Organic Waste",
            "Electronic Waste",
            "Other"
        ]
        priorities = ["Low", "Medium", "High"]
        statuses = ["Pending", "In Progress", "Resolved"]

        category_options = "".join(
            f'<option value="{x}" {"selected" if report["category"] == x else ""}>{x}</option>'
            for x in categories
        )
        priority_options = "".join(
            f'<option value="{x}" {"selected" if report["priority"] == x else ""}>{x}</option>'
            for x in priorities
        )
        status_options = "".join(
            f'<option value="{x}" {"selected" if report["status"] == x else ""}>{x}</option>'
            for x in statuses
        )

        html = load_template("edit_report.html")
        html = html.replace("{{REPORT_ID}}", str(report["id"]))
        html = html.replace("{{LOCATION}}", escape_html(report["location"]))
        html = html.replace("{{DESCRIPTION}}", escape_html(report["description"]))
        html = html.replace("{{CATEGORY_OPTIONS}}", category_options)
        html = html.replace("{{PRIORITY_OPTIONS}}", priority_options)
        html = html.replace("{{STATUS_OPTIONS}}", status_options)

        return send_html(self, html)

    def analytics_page(self):
        user = get_logged_in_user(self)
        if not user:
            return redirect(self, "/login")

        create_charts()

        connection = get_connection()

        total = connection.execute(
            "SELECT COUNT(*) AS total FROM waste_reports"
        ).fetchone()["total"]

        pending = connection.execute(
            "SELECT COUNT(*) AS total FROM waste_reports WHERE status = 'Pending'"
        ).fetchone()["total"]

        in_progress = connection.execute(
            "SELECT COUNT(*) AS total FROM waste_reports WHERE status = 'In Progress'"
        ).fetchone()["total"]

        resolved = connection.execute(
            "SELECT COUNT(*) AS total FROM waste_reports WHERE status = 'Resolved'"
        ).fetchone()["total"]

        locations = connection.execute("""
            SELECT location, COUNT(*) AS total
            FROM waste_reports
            GROUP BY location
            ORDER BY total DESC
        """).fetchall()

        categories = connection.execute("""
            SELECT category, COUNT(*) AS total
            FROM waste_reports
            GROUP BY category
            ORDER BY total DESC
        """).fetchall()

        priorities = connection.execute("""
            SELECT priority, COUNT(*) AS total
            FROM waste_reports
            GROUP BY priority
            ORDER BY total DESC
        """).fetchall()

        connection.close()

        def make_rows(rows):
            if not rows:
                return "<p>No data available yet.</p>"
            return "".join(
                f"""
                <div class="analytics-row">
                    <span>{escape_html(row[0])}</span>
                    <strong>{row[1]}</strong>
                </div>
                """
                for row in rows
            )

        html = load_template("analytics.html")
        html = html.replace("{{TOTAL_REPORTS}}", str(total))
        html = html.replace("{{PENDING_REPORTS}}", str(pending))
        html = html.replace("{{IN_PROGRESS_REPORTS}}", str(in_progress))
        html = html.replace("{{RESOLVED_REPORTS}}", str(resolved))
        html = html.replace("{{LOCATION_ANALYTICS}}", make_rows(locations))
        html = html.replace("{{CATEGORY_ANALYTICS}}", make_rows(categories))
        html = html.replace("{{PRIORITY_ANALYTICS}}", make_rows(priorities))

        if MATPLOTLIB_AVAILABLE:
            chart_html = """
            <div class="chart-grid">
                <div class="chart-card">
                    <h3>Status</h3>
                    <img src="/charts/status_chart.png" alt="Reports by status">
                </div>
                <div class="chart-card">
                    <h3>Priority</h3>
                    <img src="/charts/priority_chart.png" alt="Reports by priority">
                </div>
                <div class="chart-card">
                    <h3>Category</h3>
                    <img src="/charts/category_chart.png" alt="Reports by category">
                </div>
                <div class="chart-card">
                    <h3>Top Locations</h3>
                    <img src="/charts/location_chart.png" alt="Top reported locations">
                </div>
            </div>
            """
        else:
            chart_html = """
            <div class="no-reports">
                <p>Matplotlib is not installed. Run: pip install matplotlib</p>
            </div>
            """

        html = html.replace("{{CHARTS}}", chart_html)
        return send_html(self, html)

    def api_reports(self):
        connection = get_connection()
        rows = connection.execute("""
            SELECT id, user_id, location, category, description,
                   priority, status, reported_at, updated_at
            FROM waste_reports
            ORDER BY id DESC
        """).fetchall()
        connection.close()

        return send_json(
            self,
            [dict(row) for row in rows]
        )

    def api_statistics(self):
        connection = get_connection()

        stats = {}
        for status in ("Pending", "In Progress", "Resolved"):
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM waste_reports WHERE status = ?",
                (status,)
            ).fetchone()
            stats[status] = row["total"]

        stats["Total"] = connection.execute(
            "SELECT COUNT(*) AS total FROM waste_reports"
        ).fetchone()["total"]

        connection.close()

        return send_json(self, stats)

    def do_POST(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        form = parse_form(self)

        try:
            if path == "/register":
                return self.register(form)

            if path == "/login":
                return self.login(form)

            if path == "/forgot-password":
                return self.forgot_password(form)

            if path == "/submit-report":
                return self.submit_report(form)

            if path == "/update-status":
                return self.update_status(form)

            if path == "/edit-report":
                return self.edit_report(form)

            if path == "/delete-report":
                return self.delete_report(form)

            if path == "/import-json":
                return self.import_json(form)

            return send_html(
                self,
                render_message(
                    "404",
                    "POST route not found.",
                    "/",
                    "Go Home"
                ),
                404
            )

        except sqlite3.Error as error:
            logging.exception("Database error: %s", error)
            return send_html(
                self,
                render_message(
                    "Database Error",
                    "Something went wrong while accessing the database.",
                    "/",
                    "Go Home"
                ),
                500
            )
        except Exception as error:
            logging.exception("Application error: %s", error)
            return send_html(
                self,
                render_message(
                    "Application Error",
                    "Something unexpected happened. Check the log file.",
                    "/",
                    "Go Home"
                ),
                500
            )

    def register(self, form):
        full_name = form.get("full_name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")

        if not full_name or not email or not password:
            return send_html(
                self,
                render_message(
                    "Registration Error",
                    "Please fill in all fields.",
                    "/register",
                    "Try Again"
                ),
                400
            )

        connection = get_connection()

        try:
            cursor = connection.execute(
                """
                INSERT INTO users
                    (full_name, email, password, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    full_name,
                    email,
                    hash_password(password),
                    now()
                )
            )
            connection.commit()
            user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            connection.close()
            return send_html(
                self,
                render_message(
                    "Registration Error",
                    "An account with that email already exists.",
                    "/register",
                    "Try Again"
                ),
                400
            )

        connection.close()

        session_id = secrets.token_hex(24)
        sessions[session_id] = user_id
        log_activity(user_id, "REGISTER", "Created an account")

        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            f"session_id={session_id}; Path=/; HttpOnly"
        )
        self.end_headers()

    def login(self, form):
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")

        connection = get_connection()
        user = connection.execute(
            """
            SELECT id, full_name, email, password
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()
        connection.close()

        if not user or not verify_password(password, user["password"]):
            return send_html(
                self,
                render_message(
                    "Login Failed",
                    "Incorrect email or password.",
                    "/login",
                    "Try Again"
                ),
                401
            )

        session_id = secrets.token_hex(24)
        sessions[session_id] = user["id"]
        log_activity(user["id"], "LOGIN", "User logged in")

        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            f"session_id={session_id}; Path=/; HttpOnly"
        )
        self.end_headers()

    def forgot_password(self, form):
        email = form.get("email", "").strip().lower()
        new_password = form.get("new_password", "")

        if not email or not new_password:
            return send_html(
                self,
                render_message(
                    "Password Reset",
                    "Please enter your email and new password.",
                    "/forgot-password",
                    "Try Again"
                ),
                400
            )

        connection = get_connection()
        user = connection.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if not user:
            connection.close()
            return send_html(
                self,
                render_message(
                    "Password Reset Failed",
                    "No account was found with that email.",
                    "/forgot-password",
                    "Try Again"
                ),
                404
            )

        connection.execute(
            "UPDATE users SET password = ? WHERE email = ?",
            (hash_password(new_password), email)
        )
        connection.commit()
        connection.close()

        log_activity(user["id"], "PASSWORD_RESET", "Password was reset")

        return send_html(
            self,
            render_message(
                "Password Reset Successful",
                "Your password has been changed.",
                "/login",
                "Login"
            )
        )

    def submit_report(self, form):
        user = get_logged_in_user(self)
        if not user:
            return redirect(self, "/login")

        location = form.get("location", "").strip()
        category = form.get("category", "").strip()
        description = form.get("description", "").strip()
        priority = form.get("priority", "").strip()

        if not all([location, category, description, priority]):
            return send_html(
                self,
                render_message(
                    "Report Error",
                    "Please complete every report field.",
                    "/report",
                    "Try Again"
                ),
                400
            )

        if priority not in ("Low", "Medium", "High"):
            return send_html(
                self,
                render_message(
                    "Report Error",
                    "Invalid priority selected.",
                    "/report",
                    "Try Again"
                ),
                400
            )

        connection = get_connection()
        connection.execute(
            """
            INSERT INTO waste_reports
                (user_id, location, category, description,
                 priority, status, reported_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                location,
                category,
                description,
                priority,
                "Pending",
                now(),
                now()
            )
        )
        connection.commit()
        connection.close()

        log_activity(
            user["id"],
            "CREATE_REPORT",
            f"Location: {location}; Category: {category}"
        )

        return redirect(self, "/reports")

    def update_status(self, form):
        user = get_logged_in_user(self)
        if not user:
            return redirect(self, "/login")

        report_id = form.get("report_id", "")
        status = form.get("status", "")

        if not report_id.isdigit() or status not in (
            "Pending", "In Progress", "Resolved"
        ):
            return redirect(self, "/reports")

        connection = get_connection()
        connection.execute(
            """
            UPDATE waste_reports
            SET status = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (status, now(), int(report_id), user["id"])
        )
        connection.commit()
        connection.close()

        log_activity(
            user["id"],
            "UPDATE_STATUS",
            f"Report {report_id} changed to {status}"
        )

        return redirect(self, "/reports")

    def edit_report(self, form):
        user = get_logged_in_user(self)
        if not user:
            return redirect(self, "/login")

        report_id = form.get("report_id", "")
        if not report_id.isdigit():
            return redirect(self, "/reports")

        connection = get_connection()

        connection.execute(
            """
            UPDATE waste_reports
            SET location = ?,
                category = ?,
                description = ?,
                priority = ?,
                status = ?,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                form.get("location", "").strip(),
                form.get("category", "").strip(),
                form.get("description", "").strip(),
                form.get("priority", "").strip(),
                form.get("status", "").strip(),
                now(),
                int(report_id),
                user["id"]
            )
        )

        connection.commit()
        connection.close()

        log_activity(
            user["id"],
            "EDIT_REPORT",
            f"Edited report {report_id}"
        )

        return redirect(self, "/reports")

    def delete_report(self, form):
        user = get_logged_in_user(self)
        if not user:
            return redirect(self, "/login")

        report_id = form.get("report_id", "")
        if not report_id.isdigit():
            return redirect(self, "/reports")

        connection = get_connection()
        connection.execute(
            """
            DELETE FROM waste_reports
            WHERE id = ? AND user_id = ?
            """,
            (int(report_id), user["id"])
        )
        connection.commit()
        connection.close()

        log_activity(
            user["id"],
            "DELETE_REPORT",
            f"Deleted report {report_id}"
        )

        return redirect(self, "/reports")

    def import_json(self, form):
        user = get_logged_in_user(self)
        if not user:
            return redirect(self, "/login")

        json_text = form.get("json_data", "").strip()

        try:
            records = json.loads(json_text)
            if not isinstance(records, list):
                raise ValueError("JSON must contain a list of reports.")

            connection = get_connection()
            imported = 0

            for item in records:
                location = str(item.get("location", "")).strip()
                category = str(item.get("category", "Other")).strip()
                description = str(item.get("description", "")).strip()
                priority = str(item.get("priority", "Medium")).strip()
                status = str(item.get("status", "Pending")).strip()

                if not location or not description:
                    continue

                if priority not in ("Low", "Medium", "High"):
                    priority = "Medium"

                if status not in ("Pending", "In Progress", "Resolved"):
                    status = "Pending"

                connection.execute(
                    """
                    INSERT INTO waste_reports
                        (user_id, location, category, description,
                         priority, status, reported_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user["id"],
                        location,
                        category,
                        description,
                        priority,
                        status,
                        now(),
                        now()
                    )
                )
                imported += 1

            connection.commit()
            connection.close()

            log_activity(
                user["id"],
                "IMPORT_JSON",
                f"Imported {imported} reports"
            )

            return send_html(
                self,
                render_message(
                    "Import Successful",
                    f"{imported} report(s) were imported.",
                    "/reports",
                    "View Reports"
                )
            )

        except (json.JSONDecodeError, ValueError) as error:
            return send_html(
                self,
                render_message(
                    "Import Error",
                    str(error),
                    "/reports",
                    "Back to Reports"
                ),
                400
            )


def export_csv():
    connection = get_connection()
    rows = connection.execute("""
        SELECT
            waste_reports.id,
            users.full_name,
            users.email,
            waste_reports.location,
            waste_reports.category,
            waste_reports.description,
            waste_reports.priority,
            waste_reports.status,
            waste_reports.reported_at,
            waste_reports.updated_at
        FROM waste_reports
        LEFT JOIN users ON users.id = waste_reports.user_id
        ORDER BY waste_reports.id DESC
    """).fetchall()
    connection.close()

    with open(
        "waste_reports_export.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as file:
        writer = csv.writer(file)
        writer.writerow([
            "ID", "User", "Email", "Location", "Category",
            "Description", "Priority", "Status",
            "Reported At", "Updated At"
        ])

        for row in rows:
            writer.writerow(list(row))

    print("CSV exported to waste_reports_export.csv")


def export_json():
    connection = get_connection()
    rows = connection.execute("""
        SELECT
            id, user_id, location, category, description,
            priority, status, reported_at, updated_at
        FROM waste_reports
        ORDER BY id DESC
    """).fetchall()
    connection.close()

    with open(
        "waste_reports_export.json",
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            [dict(row) for row in rows],
            file,
            indent=4
        )

    print("JSON exported to waste_reports_export.json")


def main():
    parser = argparse.ArgumentParser(
        description="Waste Management Reporting and Monitoring System"
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Server host"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Server port"
    )

    parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export reports to CSV and exit"
    )

    parser.add_argument(
        "--export-json",
        action="store_true",
        help="Export reports to JSON and exit"
    )

    args = parser.parse_args()

    create_database()

    if args.export_csv:
        export_csv()
        return

    if args.export_json:
        export_json()
        return

    os.makedirs(CHART_DIR, exist_ok=True)

    server = ThreadingHTTPServer(
        (args.host, args.port),
        WasteManagementHandler
    )

    print(
        f"Waste Management System running at "
        f"http://{args.host}:{args.port}"
    )
    print("Press Ctrl+C to stop the server.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
