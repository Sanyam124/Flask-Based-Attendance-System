with open('app.py', 'r') as f:
    content = f.read()

# Remove ssl_context line
content = content.replace("        ssl_context=('cert.pem', 'key.pem'),\n", "")

# Clean up the comment
content = content.replace(
    "    # Using eventlet or gevent would be better for Production, \n    # but for local dev with SSL, the standard server is often easier.\n",
    "    # For production SSL, use a reverse proxy (e.g., nginx).\n"
)

# Clean up inline comment on use_reloader
content = content.replace(
    "        use_reloader=False # Disabling reloader can help with 'WERKZEUG_SERVER_FD' errors in some IDEs/Venvs",
    "        use_reloader=False"
)

with open('app.py', 'w') as f:
    f.write(content)

print("Done - ssl_context removed")
