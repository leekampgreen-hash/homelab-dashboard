import os
from dotenv import load_dotenv

load_dotenv()

ESXI_HOST = os.getenv("ESXI_HOST")
ESXI_USERNAME = os.getenv("ESXI_USERNAME")
ESXI_PASSWORD = os.getenv("ESXI_PASSWORD")
