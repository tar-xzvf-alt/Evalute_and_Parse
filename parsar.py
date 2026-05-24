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

    searched_posts = GetPosts(domain, dt1, dt2, words)
    start = time.time()
    offset = 0
    for post in searched_posts:
        offset1 = 0
        while offset1 < post['comments']['count']:

            print(offset)
            time.sleep(0.5)
            code2 = """return API.wall.getComments({"owner_id": """ + f"{post['owner_id']}" + f""","post_id": {post['id']}""" + ""","v": \"5.131\"""" + f""","count": 100""" + """});"""

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


def GetPosts(domain, dt1, dt2, words):

    token = "10e12b7710e12b7710e12b777413dfe46a110e110e12b77796a0e3ef3773f2ac46557be"
             
    version = "5.131"

    searched_posts = []
    all_searched_posts = []

    url = f'https://api.vk.com/method/wall.get?access_token={token}&v=5.131&domain={domain}'
    try:
        posts_response = requests.get(url)
    except:
        print("Сообщество пропущено")
    else:
        posts_count = posts_response.json()['response']['count']

        print(f"Всего постов в группе:{posts_count}")

        offset = 0
        start = time.time()

        RegularExpression = ''

        keywords = words.lower().split(',')

        if len(keywords[0].split()) > 1:
            for keyword in keywords[0].split():
                word = snowball.stem(keyword)
                RegularExpression += word+'.*'
            RegularExpression += '|'

            for keyword in reversed(keywords[0].split()):
                word = snowball.stem(keyword)
                RegularExpression += word + '.*'
        else:
            RegularExpression += snowball.stem(keywords[0])

        if len(keywords) > 1:
            for i in range(1, len(keywords)):

                RegularExpression += '|'

                for keyword in keywords[i].split():
                    word = snowball.stem(keyword)
                    RegularExpression += word + '.*'

                RegularExpression += '|'

                for keyword in keywords[i].split():
                    word = snowball.stem(keyword)
                    RegularExpression += word + '.*'

        while offset < posts_count:

            code1 = """return API.wall.get({"domain": """ + f"\"{domain}\"" + ""","offset": """ + str(
                offset) + ""","count": 100,"extended": 0,"v": "5.131"});"""

            response1 = requests.post("https://api.vk.com/method/execute",
                                      data={
                                          "code": code1,
                                          "access_token": token,
                                          "v": version
                                      }
                                      )
            data1 = response1.json()['response']['items']

            if data1[50]['date'] < dt1:
                break

            for post in data1:
                if (re.search(rf"{RegularExpression}", rf"{post['text'].lower()}") != None) and (post['date'] < dt2) and (post['date'] > dt1):
                    searched_posts.append(post)

            offset += 100
            end = time.time() - start

            all_searched_posts.extend(searched_posts)
            print(f"Обработано {offset} постов за {end} секунд из них {len(all_searched_posts)} отобрано")
            searched_posts.clear()
    finally:
        return all_searched_posts

def file_writer(data, theme, dt1, dt2,output_path):
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    i = 1
    for post in data:
        if (post['date'] < dt2) and (post['date'] > dt1) and (post['text'] != ' '):
            worksheet['A'+str(i)] = post['text']
            i += 1

    filename = theme + ".xlsx"
    output_path_final = os.path.join(output_path, filename)
    workbook.save(output_path_final)



def ParseGroupsPosts(city, groups, dt1, dt2, region, minimal, words):
    posts = []
    for group in groups:
        #print(f"Группа {group['name']}")
        posts += GetPosts(group['screen_name'], dt1, dt2, words)
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

    groups_posts = ParseGroupsPosts(city, groups, dt1, dt2, region, minimal, words)

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
