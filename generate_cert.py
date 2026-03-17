from OpenSSL import crypto
import os

# Define the names for your certificate files
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

def generate_self_signed_cert():
    """
    Generates a self-signed SSL certificate and a private key.
    Saves them as cert.pem and key.pem in the current directory.
    """
    print("Generating self-signed certificate...")

    # 1. Create a new private key
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 4096)

    # 2. Create a self-signed certificate
    cert = crypto.X509()
    
    # Set certificate properties (can be anything for local development)
    cert.get_subject().C = "IN"
    cert.get_subject().ST = "State"
    cert.get_subject().L = "City"
    cert.get_subject().O = "My Project"
    cert.get_subject().OU = "Development"
    cert.get_subject().CN = "localhost" # Common Name
    
    # Set serial number and validity period
    cert.set_serial_number(1000)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(365 * 24 * 60 * 60) # Valid for 1 year

    # Set the issuer to be the same as the subject (self-signed)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.sign(key, 'sha256')

    # 3. Save the certificate and key to files
    with open(CERT_FILE, "wt") as f:
        f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode("utf-8"))
        print(f"Successfully created certificate: {os.path.abspath(CERT_FILE)}")

    with open(KEY_FILE, "wt") as f:
        f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, key).decode("utf-8"))
        print(f"Successfully created private key: {os.path.abspath(KEY_FILE)}")

if __name__ == '__main__':
    generate_self_signed_cert()