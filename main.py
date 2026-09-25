from http.server import SimpleHTTPRequestHandler, HTTPServer
import os


PORT = 8000


class WasteManagementHandler(SimpleHTTPRequestHandler):

    def do_GET(self):

        if self.path == "/":
            self.path = "/templates/index.html"

        return super().do_GET()


server = HTTPServer(("localhost", PORT), WasteManagementHandler)

print("======================================")
print("   WASTE MANAGEMENT SYSTEM")
print("======================================")
print(f"\nWebsite running at: http://localhost:{PORT}")
print("Press Ctrl + C to stop the server.")

server.serve_forever()