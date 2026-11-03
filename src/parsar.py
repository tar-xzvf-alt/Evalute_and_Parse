#coding: utf8
import os
import sys

import requests
import time
import re
from nltk.stem import SnowballStemmer
import openpyxl

snowball = SnowballStemmer(language="russian")


def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def GetComments(domain, dt1, dt2, minimal, words,user_token):
    version = "5.131"

    searched_comments = []
    all_comments = []

    searched_posts = GetPosts(domain, dt1, dt2, words, user_token)
    start = time.time()
    offset = 0
    for post in searched_posts:
        offset1 = 0
        while offset1 < post['comments']['count']:

            print(offset)
            time.sleep(0.5)
            code2 = """return API.wall.getComments({"owner_id": """ + f"{post['owner_id']}" + f""","post_id": {post['id']}""" + ""","v": \"5.131\"""" + f""","count": 100,"offset": {offset1}""" + """});"""

            response2 = requests.post("https://api.vk.com/method/execute",
                                      data={
                                          "code": code2,
                                          "access_token": user_token,
                                          "v": version
                                      }
                                      )
            comments = response2.json()['response']['items']

            for comment in comments:
                if len(comment['text'].split()) >= int(minimal):
                    searched_comments.append(comment)
            all_comments.extend(searched_comments)
            offset1 += 100
            searched_comments.clear()
        offset += post['comments']['count']

    end = time.time() - start

    print(f"Обработано {offset} комментов за {end} секунд из них {len(all_comments)} отобрано")

    return all_comments


def GetPosts(domain, dt1, dt2, words, user_token=None, minimal=0):
    """Compatibility adapter for the old post/comment workflow."""
    from vk_collection import VKClient, WallPeriod

    if user_token is None:
        with open(resource_path('vk_token.txt'), encoding='utf-8') as token_file:
            user_token = token_file.read().strip()
    client = VKClient(user_token)
    try:
        if str(domain).isdigit():
            group_id = int(domain)
        else:
            groups = client.call('groups.getById', group_ids=str(domain))
            group_id = groups[0]['id']
        terms = [term.strip().casefold() for term in words.split(',') if term.strip()]
        return [post for post in WallPeriod(client, group_id, dt1, dt2).posts()
                if len(post.get('text', '').split()) >= int(minimal)
                and (not terms or any(term in post.get('text', '').casefold() for term in terms))]
    finally:
        client.session.close()

def file_writer(data, theme, dt1, dt2,output_path):
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    i = 1
    for post in data:
        if (post['date'] < dt2) and (post['date'] >= dt1) and (post['text'] != ' '):
            worksheet['A'+str(i)] = post['text']
            i += 1

    filename = theme + ".xlsx"
    output_path_final = os.path.join(output_path, filename)
    workbook.save(output_path_final)



def ParseGroupsPosts(city, groups, dt1, dt2, region, minimal, words, user_token=None):
    posts = []
    for group in groups:
        #print(f"Группа {group['name']}")
        posts += GetPosts(group['id'], dt1, dt2, words, user_token, minimal)
    return posts


def ParseGroupsComments(groups, dt1, dt2, minimal, words,user_token):
    comments = []
    for group in groups:
        print(f"Группа {group['name']}")
        comments += GetComments(group['screen_name'], dt1, dt2, minimal, words,user_token)
    return comments


def MainParsePosts(city, dt1, dt2, count, region, minimal, words,user_token):

    version = "5.131"

    response = requests.get("https://api.vk.com/method/groups.search",
                            params={
                                "access_token": user_token,
                                "v": version,
                                "q": f"{city}",
                                "type": "page",
                                "sort": 0,
                                "count": int(count),
                            }
                            )
    print("here")

    groups = response.json()['response']['items']

    groups_posts = ParseGroupsPosts(city, groups, dt1, dt2, region, minimal, words, user_token)

    return groups_posts


def MainParseComments(city, dt1, dt2, count, filename, minimal,words,user_token):

    version = "5.131"

    response = requests.get("https://api.vk.com/method/groups.search",
                            params={
                                "access_token": user_token,
                                "v": version,
                                "q": f"{city}",
                                "type": "page",
                                "sort": 1,
                                "count": int(count),
                            }
                            )
    groups = response.json()['response']['items']

    groups_comments = ParseGroupsComments(groups, dt1, dt2, minimal, words,user_token)

    return groups_comments


# Функция для проверки токена через VK API
def check_vk_token(token):
    try:
        response = requests.get(
            'https://api.vk.com/method/users.get',
            params={'access_token': token, 'v': '5.131'}
        )
        data = response.json()

        return response.status_code == 200 and 'error' not in data
    except Exception as e:
        print(f"Ошибка при проверке токена: {e}")
        return False
