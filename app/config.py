import os
from dotenv import load_dotenv

load_dotenv()

ESXI_HOST = os.getenv("ESXI_HOST")
ESXI_USERNAME = os.getenv("ESXI_USERNAME")
ESXI_PASSWORD = os.getenv("ESXI_PASSWORD")

ILO_HOST = os.getenv("ILO_HOST")
ILO_USERNAME = os.getenv("ILO_USERNAME")
ILO_PASSWORD = os.getenv("ILO_PASSWORD")
