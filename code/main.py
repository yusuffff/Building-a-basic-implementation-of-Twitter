import datetime
import random
from operator import itemgetter
from flask import Flask, render_template, request, redirect, Response
from google.cloud import datastore, storage
import google.oauth2.id_token
from google.auth.transport import requests
import local_constants

app = Flask(__name__)

# get access to the datastore client so we can add and store data in the datastore
datastore_client = datastore.Client()

# get access to a request adapter for firebase as we will need this to authenticate users
firebase_request_adapter = requests.Request()


def create_new_user(claims):
    entity_key = datastore_client.key('UserInfo', claims['email'])
    entity = datastore.Entity(key = entity_key)
    entity.update({
    'email': claims['email'],
    'name': claims['name'],
    'username':'',
    'profile': '',
    'creation_date': datetime.datetime.now(),
    'my_tweets':[],
    'followed_by':[],
    'my_following':[]
    })
    datastore_client.put(entity)
    
def retrieve_user(user_email):
    entity_key = datastore_client.key('UserInfo', user_email)
    entity = datastore_client.get(entity_key)
    return entity


@app.route('/submit_user_changes', methods=['POST'])
def edit_profile_submit():
    user_email = request.form['user']
    user = retrieve_user(user_email)
    profile = request.form['profile']
    name = request.form['name']
    
    user.update({
        'name':name,
        'profile': profile
    })
    
    datastore_client.put(user)
    
    return redirect('/')

def get_potentional_following(user):
    my_following = user['my_following']
    query = datastore_client.query(kind='UserInfo')
    users = query.fetch()
    potentional = []
    for user in users:
        if user['username'] == '' or user['email'] in my_following:
            continue
        else:
            potentional.append(user)
    return potentional
    
    
def search(term):
    user = None
    tweets = None
    
    query = datastore_client.query(kind='UserInfo')
    query.add_filter('username', '=', term)
    user = query.fetch()
    
    query = datastore_client.query(kind='Tweets')
    query.add_filter('query', '=', term)
    tweets = query.fetch()
    
    return list(user), list(tweets)
    

@app.route('/search', methods=['POST'])
def search_user_tweets():
    user_email = request.form['user']
    user = retrieve_user(user_email)
    query = request.form['term']
    user_search, tweets = search(query)
    if user_search:
        user_search = user_search[0]
        print(f'USER SEARCH {user_search}')
    else:
        user_search = None
    if tweets:
        print(f'TWeets SEARCH {tweets}')
    else:
        tweets = None
        
    tweets_user = retrieve_timeline(user)
    
    return render_template('index.html', user_data=user, user_search=user_search, tweets_search=tweets, tweets=tweets_user)
    

def create_tweet(tweet, user):
    tweet_id = random.getrandbits(63)
    entity_key = datastore_client.key('Tweets', tweet_id)
    entity = datastore.Entity(key = entity_key)
    search_tweet_list = []
    search_tweet = ''
    for char in tweet:
        search_tweet += char
        search_tweet_list.append(search_tweet)
            
    entity.update({
    'user': user['email'],
    'username': user['username'],
    'text': tweet,
    'file': '',
    'query': search_tweet_list,
    'date': datetime.datetime.now()
    })
    datastore_client.put(entity)
    
    tweets_by_user = user['my_tweets']
    tweets_by_user.append(tweet_id)
    user.update({
        'my_tweets': tweets_by_user
    })
    datastore_client.put(user)

def retrieve_tweet(tweet_id):
    entity_key = datastore_client.key('Tweets', int(tweet_id))
    entity = datastore_client.get(entity_key)
    return entity

def retrieve_timeline(user):
    following_users = user['my_following']
    ids = []
    for user_email in following_users:
        user_details = retrieve_user(user_email)
        ids.extend(user_details['my_tweets'])
    ids.extend(user['my_tweets'])
    tweets = []
    for id in ids:
        tweets.append(retrieve_tweet(int(id)))
        
    tweets = sorted(tweets, key=itemgetter('date'), reverse=True) 
    print(tweets)
    return tweets

def addFile(file):
    storage_client = storage.Client(project=local_constants.PROJECT_NAME)
    bucket = storage_client.bucket(local_constants.PROJECT_STORAGE_BUCKET)
    blob = bucket.blob(file.filename)
    blob.upload_from_file(file)
    
def downloadBlob(filename):
    storage_client = storage.Client(project=local_constants.PROJECT_NAME)
    bucket = storage_client.bucket(local_constants.PROJECT_STORAGE_BUCKET)
    blob = bucket.blob(filename)
    return blob.download_as_bytes()

@app.route('/upload_file', methods=['post'])
def uploadFileHandler():
    id_token = request.cookies.get("token")
    tweet_id = request.form['tweet']
    tweet = retrieve_tweet(int(tweet_id))
    if id_token:
        try:
            file = request.files['file_name']
            if file.filename.endswith('.jpeg') or file.filename.endswith('.png'):
                addFile(file)
                tweet.update({
                    'file':file.filename
                })
                datastore_client.put(tweet)
            else:
                return redirect('/')
        except ValueError as exc:
            error_message = str(exc)
    return redirect('/')

@app.route('/download_file/<string:filename>', methods=['POST'])
def downloadFile(filename):
    id_token = request.cookies.get("token")
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(id_token,
            firebase_request_adapter)
        except ValueError as exc:
            error_message = str(exc)
    return Response(downloadBlob(filename), mimetype='application/octet-stream')


@app.route('/tweet/delete', methods=['POST'])
def tweet_delete():
    user_email = request.form['user']
    user = retrieve_user(user_email)
    tweet_id = request.form['tweet_id']
    tweet = retrieve_tweet(tweet_id)
    
    my_tweets = user['my_tweets']
    my_tweets.remove(int(tweet_id))
    user.update({
        'my_tweets':my_tweets
    })
    datastore_client.put(user)
    datastore_client.delete(tweet)
    return redirect('/')
    

@app.route('/tweet/edit/submit', methods=['POST'])
def tweet_edit_submit():
    user_email = request.form['user']
    user = retrieve_user(user_email)
    tweet_id = request.form['tweet_id']
    tweet = retrieve_tweet(tweet_id)
    
    new_text = request.form['tweet']
    
    search_tweet_list = []
    search_tweet = ''
    for char in new_text:
        search_tweet += char
        search_tweet_list.append(search_tweet)
    tweet.update({
        'text':new_text,
        'query':search_tweet_list
    })
    
    datastore_client.put(tweet)
    
    return redirect('/')
    

@app.route('/tweet/edit', methods=['POST'])
def tweet_edit():
    user_email = request.form['user']
    user = retrieve_user(user_email)
    tweet_id = request.form['tweet_id']
    tweet = retrieve_tweet(tweet_id)
    
    return render_template('edit_tweet.html', user_data=user, tweet=tweet)
    
    
        
@app.route('/follow_user', methods=['POST'])
def follow_user():
    user_email_login = request.form['user_login']
    user_login = retrieve_user(user_email_login)
    user_email_profile = request.form['profile']
    user_profile = retrieve_user(user_email_profile)
    
    following = user_login['my_following']
    following.append(user_profile['email'])
    user_login.update({
        'my_following': following
    })
    datastore_client.put(user_login)
    
    followed_by = user_profile['followed_by']
    followed_by.append(user_login['email'])
    user_profile.update({
        'followed_by': followed_by
    })
    
    datastore_client.put(user_profile)
    
    return render_template('profile_page.html', profile=user_profile, user_data=user_login, tweets=get_tweets(user_profile))

@app.route('/unfollow_user', methods=['POST'])
def unfollow_user():
    user_email_login = request.form['user_login']
    user_login = retrieve_user(user_email_login)
    user_email_profile = request.form['profile']
    user_profile = retrieve_user(user_email_profile)
    
    following = user_login['my_following']
    following.remove(user_profile['email'])
    user_login.update({
        'my_following': following
    })
    datastore_client.put(user_login)
    
    followed_by = user_profile['followed_by']
    followed_by.remove(user_login['email'])
    user_profile.update({
        'followed_by': followed_by
    })
    
    datastore_client.put(user_profile)
    
    return render_template('profile_page.html', profile=user_profile, user_data=user_login, tweets=get_tweets(user_profile))


@app.route('/tweet', methods=['POST'])
def tweet():
    user_email = request.form['user']
    user = retrieve_user(user_email)
    tweet = request.form['tweet']
    create_tweet(tweet, user)
    return redirect('/')

def get_tweets(user):
    tweets = user['my_tweets']
    tweets_obj = []
    for tweet_id in tweets:
        tweet_obj = retrieve_tweet(tweet_id)
        tweets_obj.append(tweet_obj)
    return tweets_obj
    
@app.route('/profile_page', methods=['POST'])
def route_profile():
    user_email_login = request.form['user_login']
    user_login = retrieve_user(user_email_login)
    user_email_search = request.form['user_search']
    user_search = retrieve_user(user_email_search)
    print(f'USER LOGIN {user_login}')
    print(f'USER PROFILE {user_search}')
    print(f'TWeets {get_tweets(user_search)}')
    return render_template('profile_page.html', profile=user_search, user_data=user_login, tweets=get_tweets(user_search))

@app.route('/edit_user', methods=['POST'])
def edit_profile():
    user_email = request.form['user']
    user = retrieve_user(user_email)
    return render_template('edit_user.html', user_data=user)

@app.route('/set_up_user', methods=['POST'])
def set_up_username():
    user_email = request.form['user']
    user = retrieve_user(user_email)
    username = request.form['username']
    user.update({
        'username': username
    })
    datastore_client.put(user)
    return redirect('/')

@app.route('/')
def root():
    # query firebase for the request token and set other variables to none for now
    id_token = request.cookies.get("token")
    username = request.cookies.get("username")
    error_message = None
    claims = None
    user_info = None
    user_search = None
    tweets_search = None
    tweets = None
    potentional = None
    
    print(f"ID TOKEN {id_token}")
    if id_token:
        try:
            claims = google.oauth2.id_token.verify_firebase_token(id_token, firebase_request_adapter)
            if retrieve_user(claims['email']) == None:
                claims['name'] = username
                create_new_user(claims)
                user_info = retrieve_user(claims['email'])
                print(user_info)
                return render_template('set_username.html', user_data = user_info)
            else:
                user_info = retrieve_user(claims['email'])
            print(f"USER INFO {user_info}")
            tweets = retrieve_timeline(user_info)
            potentional = get_potentional_following(user_info)
            if user_info['username'] == '':
                return render_template('set_username.html', user_data = user_info)
        except ValueError as exc:
            error_message = str(exc)
    # if user['username'] == '':
    #     return render_template('set_username.html', user_data = user)
    # render the template with the last times we have
    return render_template('index.html', user_data=user_info, error_message=error_message, user_search=user_search, tweets_search=tweets_search, tweets=tweets, potentional=potentional)

if __name__ == '__main__':
    app.jinja_env.auto_reload = True
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.run(host='127.0.0.1', port=8080, debug=True)
    

