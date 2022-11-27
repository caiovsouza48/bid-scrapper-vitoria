from playwright.sync_api import sync_playwright
from io import BytesIO
from PIL import Image
from capmonster_python import ImageToTextTask
from captcha_solver import CaptchaSolver
from dataclasses import dataclass
from dotenv import load_dotenv
from datetime import datetime

import time
import re
import schedule
import tweepy
import requests
import urllib.parse
import os
import pytz


# Global
base_url = 'https://bid.cbf.com.br/'
bid_cache = set()

@dataclass(frozen=True)
class BidPlayer:
  """ Class for keeping track of a Bid publication"""
  name: str
  photo: str
  timestamp: str
  nickname: str
  contract_type: str
  


def publish_on_twitter(player):
  # Authenticate to Twitter
  
  #auth = tweepy.Client(bearer_token = os.getenv('TWITTER_BEARER_TOKEN'))
  auth = tweepy.OAuth1UserHandler(os.getenv('TWITTER_API_KEY'), os.getenv('TWITTER_API_SECRET'), os.getenv('TWITTER_ACCESS_TOKEN'), os.getenv('TWITTER_ACCESS_SECRET'))
  # Create API object
  api = tweepy.API(auth)

  # Download Image
  img_data = requests.get(player.photo).content
  player_image_pil = Image.open(BytesIO(img_data))
  player_name_url_escaped = urllib.parse.quote(player.name)
  buf = BytesIO()
  player_image_pil.save(buf, format='PNG')
  buf.seek(0)
  
  ret = api.media_upload(filename=f"{player_name_url_escaped}_photo.png", file=buf)
  
  # Attach media to tweet
  api.update_status(media_ids=[ret.media_id_string], status=f"{player.nickname} publicado no BID em {player.timestamp} - tipo de contrato: {player.contract_type}")
  print(f'Just published player {player} on Tweeter')
  


def resolve_captcha_img(base64_str):
    final_base64 = re.sub('^data:image/.+;base64,', '', base64_str) 
    # Debug Captcha Solver
    #solver = CaptchaSolver('browser')
    #raw_data = open(filename, 'rb').read()
    capmonster = ImageToTextTask(os.getenv('CAPMONSTER_API_KEY'))
    task_id = capmonster.create_task(base64_encoded_image=final_base64)
    result = capmonster.join_task_result(task_id)
    return result.get("text")
    #return solver.solve_captcha(raw_data)
  
def fetch_players_info(page):
  # FIXME: Hack for waiting page to Load
  page.wait_for_timeout(2000)
  
  num_results = 0
  try: 
    num_results = int(page.locator('xpath=//*[@id="display-registros"]').text_content())
  except ValueError:
    return
  
  for i in range(num_results):
    index = i + 1
    name = page.locator(f'xpath=//*[@id="lista"]/div[{index}]/div/div/div[1]').text_content()
    photo = page.locator(f'xpath=//*[@id="lista"]/div[{index}]/div/div/div[2]/img').get_attribute('src')
    timestamp = page.locator(f'xpath=//*[@id="lista"]/div[{index}]/div/div/div[3]/p[3]/strong').text_content()
    nickname = page.locator(f'xpath=//*[@id="lista"]/div[{index}]/div/div/div[3]/p[6]/strong').text_content()
    contract_type = page.locator(f'xpath=//*[@id="lista"]/div[{index}]/div/div/div[3]/p[2]/strong').text_content()
    player = BidPlayer(name=name, photo=photo, timestamp=timestamp, nickname=nickname, contract_type=contract_type)
    if player not in bid_cache:
      print(f'Found Player: {index}')
      print(f'Name = {name}')
      print(f'Photo = {photo}')
      print(f'timestamp = {timestamp}')
      print(f'nickname = {nickname}')
      print(f'contract type = {contract_type}')
      bid_cache.add(player)
      publish_on_twitter(player=player)
    

def job():
  # Do NOT Run on Weekend
  weekno = datetime.today().weekday()
  if weekno >= 5:
    print('Ladies and Gentleman, the Weeknd...')
    return
  
  now_date = datetime.now(pytz.timezone('America/Sao_Paulo'))
  hour = int(now_date.strftime("%H"))
  if hour < 9 or hour >= 18:
    print(f' hour is {hour} CBF Bid is closed, do not need to run')
    return
  
  with sync_playwright() as p:
      browser = p.webkit.launch()
      page = browser.new_page()
      page.goto(base_url)
    
      # Today Date
      current_time = datetime.now(pytz.timezone('America/Sao_Paulo'))
      current_time_string = current_time.strftime('%d/%m/%Y')
      date_input_xpath = 'xpath=//*[@id="form-busca-bid"]/div[1]/div[1]/input'
      page.locator(date_input_xpath).evaluate("el => el.removeAttribute('readonly')")
      page.locator(date_input_xpath).fill(current_time_string, force=True)
      print(f'Setting Date to {current_time_string}...')
      # State -> BA
      page.select_option('xpath=//*[@id="form-busca-bid"]/div[1]/div[2]/select', label='BA')
      print('Setting State to BA...')
      # Clube -> Vitória
      club_selector_xpath = 'xpath=//*[@id="form-busca-bid"]/div[1]/div[3]/select'
      page.locator(club_selector_xpath).evaluate("el => el.removeAttribute('disabled')")
      page.locator(club_selector_xpath).evaluate("el => el.appendChild(new Option('Vitória-BA(20018)','20018'))")
      page.locator(club_selector_xpath).evaluate("el => el.value = '20018'")
      print('Setting Club to Vitória-BA(20018)...')

      # Click Search
      page.locator('xpath=//*[@id="btn-filtro"]/i').click()
      
      #Captcha
      print('Downloading Captcha Image...')
      captcha_img_xpath = 'xpath=//*[@id="modal-captcha"]/div/div/div/div[1]/div[1]/img'
      page.wait_for_selector(captcha_img_xpath)
      
      while True:
          captcha_answer = resolve_captcha_img(page.locator(captcha_img_xpath).get_attribute('src'))
          if len(captcha_answer.replace(" ", "")) == 4:
            page.locator('xpath=//*[@id="modal-captcha"]/div/div/div/div[1]/div[2]/input').fill(captcha_answer)
            page.locator('xpath=//*[@id="btn-confirma-captcha"]').click()
            fetch_players_info(page)
            break
          else:
            print(f'Captcha Answer = {captcha_answer} not valid, retrying...')
            page.locator('xpath=//*[@id="modal-captcha"]/div/div/div/div[1]/div[1]/label/button').click()
      browser.close() 
      
def clear_bid_cache():
  bid_cache.clear()
      
if __name__ == '__main__':
  load_dotenv()
  schedule.every(3).minutes.do(job)
  schedule.every().day.at("09:00").do(clear_bid_cache)

  while True:
    schedule.run_pending()
    time.sleep(1)