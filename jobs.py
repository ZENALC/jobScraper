# Author: Mihir Shrestha
from geopy.exc import GeocoderTimedOut
from requests import get
from time import sleep
from geopy.geocoders import Nominatim
import json
import sqlite3
from typing import Tuple, List, Dict
import feedparser
import ssl
import plotly.graph_objects as go
import pandas as pd
from bs4 import BeautifulSoup


# Main function that calls the retrieve_jobs(), open_db(), create_table_jobs(),
# save_to_database(), and dump_data() functions.
def main():
    # nice job on sprint one - benign comment to test github actions
    WRITE_TO_FILE = True
    UPDATE_DATABASE = True

    githubJobs = retrieve_jobs()  # these are from github
    stackOverFlowjobs = retrieve_stack_over_flow_jobs()  # these are from stackOverFlow

    if UPDATE_DATABASE:
        databaseName = 'jobs.db'
        connection, cursor = open_db(databaseName)
        create_table(connection, cursor)
        save_to_database(githubJobs, connection, cursor)
        save_to_database(stackOverFlowjobs, connection, cursor)
        close_db(connection)

    if WRITE_TO_FILE:
        fileName = "json.txt"
        dump_data(githubJobs, fileName)


def show_map():
    databaseConnection = sqlite3.connect('jobs.db')
    df = pd.read_sql_query("SELECT * FROM jobs", databaseConnection)
    databaseConnection.commit()
    databaseConnection.close()

    fig = go.Figure(data=go.Scattergeo(
        lon=df['geo_longitude'],
        lat=df['geo_latitude'],
        text=df['Company'] + " located at " + df['Location'],
        mode='markers',
    ))

    fig.update_layout(
        title='Jobs from GitHub and StackOverFlow',
        geo_scope='world',
    )
    fig.show()


def return_geo_location(geolocator, location: str):
    found = False
    failCounter = 0
    geoLocation = None
    if not location or 'remote' in location.lower():
        return None, None
    while not found and failCounter < 10:
        try:
            if location.strip()[-2:] == "CA":
                geoLocation = geolocator.geocode(location, timeout=1, country_codes=["US"])
            else:
                geoLocation = geolocator.geocode(location, timeout=1)
            found = True
        except GeocoderTimedOut:
            failCounter += 1
            continue
    if not geoLocation:
        return None, None
    print("Just retrieved geo-information for {}".format(location))
    return geoLocation.latitude, geoLocation.longitude


# Function that retrieves the jobs from GitHub. It has a sleep function implemented,
# so that the program doesn't shoot all the requests at once to GitHub. It also checks
# if it received a 200 response code or not and reports the code back to the user if it is not 200.
# UPDATE: It is now not hard-coded to go up to 5 pages, it keeps looping through until the number
# of jobs is less than 50. Also, a new failCounter has been implemented to reduce the risks for
# an infinite loop. With the failCounter, if one page fails 3 times, then all the following pages' data will
# also not be retrieved.
def retrieve_jobs() -> List[Dict]:
    missedList = []
    jsonData = []

    endOfJobs = False
    num = 1
    failCounter = 0
    # The failCounter is implemented because if GitHub is down or the page does not exist,
    # the loop would never break.

    while not endOfJobs:
        url = "https://jobs.github.com/positions.json?page=" + str(num)
        response = get(url)
        if response.status_code == 200:
            print("Received response: {} for page {}.".format(response.status_code, num))
            newJsonData = response.json()
            jsonData += newJsonData
            if len(newJsonData) < 50:
                endOfJobs = True
            if num in missedList:
                missedList.remove(num)
                failCounter = 0
        else:
            print("Received response: {} for page {}. Trying again...".format(response.status_code, num))
            if num not in missedList:
                missedList.append(num)
            failCounter += 1
            if failCounter == 3:
                break
            # Code will try to get data from the page again for 3 attempts. It first sleeps again
            # for a half of a second to give GitHub an idea that we are friendly.
            # If it fails 3 times, it finally breaks out of the loop.
            sleep(.5)
            continue
        sleep(.5)
        num += 1

    if len(missedList) > 0:
        print("Missed data for page {} and potentially other future pages.".format(str(missedList)[1:-1]))
    else:
        print("Successfully retrieved data from all GitHub pages.")

    return jsonData


def retrieve_stack_over_flow_jobs():
    url = "https://stackoverflow.com/jobs/feed"
    # Found the conditional online. Parsing does not work if you don't run the SSL command.
    if hasattr(ssl, '_create_unverified_context'):
        ssl._create_default_https_context = ssl._create_unverified_context
    feed = feedparser.parse(url)
    totalData = []
    totalDict = {}
    for entry in feed.entries:
        totalDict["id"] = entry['id']
        totalDict["type"] = None
        totalDict["url"] = entry["link"]
        totalDict["created_at"] = entry["published"]
        totalDict["company"] = entry["author"]
        totalDict["company_url"] = None
        totalDict["title"] = entry["title"]
        totalDict["description"] = entry["summary"]
        totalDict["how_to_apply"] = None
        totalDict["company_logo"] = None
        try:
            totalDict["location"] = entry["location"]
        except KeyError:
            totalDict["location"] = None
        totalData.append(totalDict)
        totalDict = {}
    print("Successfully retrieved {} entries from StackOverFlow".format(len(feed.entries)))
    return totalData


# Simple function that dumps JSON data to a .txt file.
def dump_data(jobs: list, file_name: str):
    if not (type(jobs) is list or type(jobs) is dict):
        print("Illegal type of data. {} is of type {}. Please enter a list or dictionary.".format(jobs, type(jobs)))
        return None
    if type(jobs) is dict:
        jobs = [jobs]
    with open(file_name, 'w') as openFile:
        for job in jobs:
            json.dump(job, openFile)
    print("Successfully dumped JSON data to {}.".format(file_name))


# Simple function that dumps data to its corresponding column in the database.
def save_to_database(jobs: list, connection: sqlite3.Connection, cursor: sqlite3.Cursor):
    if not (type(jobs) is list or type(jobs) is dict):
        print("Illegal type of data. {} is of type {}. Please enter a list or dictionary.".format(jobs, type(jobs)))
        return None
    if type(jobs) is dict:
        jobs = [jobs]
    geolocator = Nominatim(user_agent="jobsRetriever")
    for job in jobs:
        if len(job) != 11:
            print("Incorrect number of arguments. Insertion failed.")
            return None
        cursor.execute("SELECT * FROM jobs WHERE jobs.id = ?", (job['id'],))
        if cursor.fetchone() is not None:
            continue
        cursor.execute("SELECT jobs.geo_latitude, jobs.geo_longitude FROM jobs WHERE jobs.location = ?", (job['location'],))
        cursorResult = cursor.fetchone()
        if cursorResult is not None:
            geolocation = cursorResult
            print("Just retrieved cached geo-information for {}.".format(job['location']))
        else:
            geolocation = return_geo_location(geolocator, job['location'])
        try:
            if job['description'] is not None:
                soup = BeautifulSoup(job['description'], features="html.parser")
                job['description'] = soup.get_text()
            if job['how_to_apply'] is not None:
                soup = BeautifulSoup(job['how_to_apply'], features="html.parser")
                job['how_to_apply'] = soup.get_text()
            cursor.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                                                                                          [job['id'],
                                                                                          job['type'],
                                                                                          job['url'],
                                                                                          job['created_at'],
                                                                                          job['company'],
                                                                                          job['company_url'],
                                                                                          job['location'],
                                                                                          job['title'],
                                                                                          job['description'],
                                                                                          job['how_to_apply'],
                                                                                          job['company_logo'],
                                                                                          geolocation[0],
                                                                                          geolocation[1]
                                                                                          ])
            commit_db(connection)
        except sqlite3.IntegrityError:
            pass
            # print("Data already exists in the table.")


# Simple function that creates a connection with a filename given and returns a connection and cursor.
def open_db(filename: str) -> Tuple[sqlite3.Connection, sqlite3.Cursor]:
    connection = sqlite3.connect(filename)  # Connects to an existing database or creates a new one.
    cursor = connection.cursor()  # We are now ready to read/write data.
    return connection, cursor


# Simple function that closes a database.
def close_db(connection: sqlite3.Connection):
    connection.commit()
    connection.close()


# Simple function that commits changes to a database.
def commit_db(connection: sqlite3.Connection):
    connection.commit()


# Simple function that creates the initial table jobs with its respective columns.
def create_table(connection: sqlite3.Connection, cursor: sqlite3.Cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS jobs(
                       id TEXT PRIMARY KEY,
                       Position_Type TEXT,
                       URL TEXT NOT NULL,
                       Created_at TEXT NOT NULL,
                       Company TEXT NOT NULL,
                       Company_URL TEXT,
                       Location TEXT,
                       Title TEXT NOT NULL,
                       Description TEXT NOT NULL,
                       How_To_Apply TEXT,
                       Company_Logo TEXT,
                       geo_latitude TEXT,
                       geo_longitude TEXT
                        );''')
    commit_db(connection)


if __name__ == "__main__":
    main()
