import datetime
import dateutil.parser
import json
import logging
import typing


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handle_course_works(request_id, response, exception, all_course_works: dict):
    logger.info("Original course work: {}".format(json.dumps(response)))
    for course_work in response.get("courseWork", []):
        all_course_works[course_work['id']] = course_work


def handle_submission(request_id, response, exception, all_submissions: typing.DefaultDict[str, list]):
    logger.info("Original submissions: {}".format(json.dumps(response)))
    submissions = response.get("studentSubmissions", [])
    for submission in submissions:
        course_work_id = submission['courseWorkId']
        all_submissions[course_work_id].append(submission)


def handle_announcement(request_id, response, exception, all_announcements):
    start = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    start = start.replace(tzinfo=datetime.timezone.utc)
    announcements = response.get("announcements", [])
    for announcement in announcements:
        update_time = dateutil.parser.isoparse(announcement['updateTime']).replace(tzinfo=datetime.timezone.utc)
        if update_time < start:
            continue
        all_announcements.append(announcement)


def handle_user_profile(request_id, response, exception, all_users):
    logger.error("Exception: {}".format(exception))
    if response:
        all_users[response['id']] = response