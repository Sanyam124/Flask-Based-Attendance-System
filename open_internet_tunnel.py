import subprocess
import re
import sys
import time

print("\n" + "*"*60)
print(" 🌐 STARTING SECURE PUBLIC INTERNET TUNNEL 🌐")
print("*"*60)
print("This will connect your local server to the global internet.")
print("You don't need to be on the same WiFi anymore!")
print("Please wait a few seconds...\n")

# Using Pinggy for extremely reliable public URLs (fixes ERR_EMPTY_RESPONSE)
# Binding exactly to 127.0.0.1 bypasses IPv6/IPv4 mix-ups which cause empty responses.
# Using localhost.run for extremely fast, sign-up-free public URLs via SSH
# Binding exactly to 127.0.0.1 bypasses IPv6/IPv4 mix-ups which cause empty responses.
cmd = [
    "ssh", 
    "-R", "80:127.0.0.1:5000",
    "-o", "StrictHostKeyChecking=no", 
    "nokey@localhost.run"
]

try:
    # Explicitly use utf-8 to prevent Windows charmap crash on SSH server box-drawing characters
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')

    for line in iter(process.stdout.readline, ''):
        # Look for the generated HTTPS URL pattern
        if "https://" in line and (".lhr.life" in line or ".localhost.run" in line):
            # Extract just the URL using regex to be safe
            match = re.search(r'(https://[a-zA-Z0-9-]+\.lhr\.life|https://[a-zA-Z0-9-]+\.localhost\.run)', line)
            if match:
                url = match.group(1)
                print("\n" + "="*65)
                print(" 🚀 SUCCESS! YOUR SYSTEM IS NOW LIVE ON THE INTERNET! 🚀")
                print("="*65)
                print(f"👉 OPEN THIS EXACT URL ON YOUR PHONE: \n   {url}")
                print("\n(You can now access your app over 4G/5G mobile data!)")
                print("="*65 + "\n")
                print("Keep this window open. Press Keyboard CTRL+C to shut down.")

except FileNotFoundError:
    print("❌ Error: SSH is not installed on this computer. Please install ngrok instead.")
except KeyboardInterrupt:
    print("\nClosing tunnel...")
    process.terminate()
    sys.exit(0)
