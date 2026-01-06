import logging
import os
import random
import re
import socket
import time

import cv2
import ddddocr
import requests
from selenium import webdriver
from selenium.common import TimeoutException, NoSuchElementException
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait


def check_network():
    """检查网络连接"""
    try:
        socket.create_connection(("www.baidu.com", 80), timeout=10)
        return True
    except OSError:
        return False


def init_selenium() -> WebDriver:
    ops = Options()
    ops.add_argument("--no-sandbox")
    ops.add_argument("--disable-dev-shm-usage")
    ops.add_argument("--disable-blink-features=AutomationControlled")
    ops.add_experimental_option("excludeSwitches", ["enable-automation"])
    ops.add_experimental_option('useAutomationExtension', False)
    
    if debug:
        ops.add_experimental_option("detach", True)
    if linux:
        ops.add_argument("--headless")
        ops.add_argument("--disable-gpu")
        ops.add_argument("--remote-debugging-port=9222")
        ops.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 代理支持
    proxy = os.environ.get('HTTP_PROXY') or os.environ.get('HTTPS_PROXY')
    if proxy and linux:
        ops.add_argument(f'--proxy-server={proxy}')
    
    chromedriver_path = "./chromedriver" if linux else "chromedriver.exe"
    
    try:
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=ops)
        
        # 隐藏webdriver特征
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
            """
        })
        
        return driver
    except Exception as e:
        logger.error(f"ChromeDriver初始化失败: {str(e)}")
        try:
            return webdriver.Chrome(options=ops)
        except Exception as e2:
            logger.error(f"备用ChromeDriver初始化也失败: {str(e2)}")
            raise


def download_image(url, filename):
    os.makedirs("temp", exist_ok=True)
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            path = os.path.join("temp", filename)
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        else:
            logger.error(f"下载图片失败！状态码: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"下载图片异常: {str(e)}")
        return False


def get_url_from_style(style):
    match = re.search(r'url\(["\']?(.*?)["\']?\)', style)
    return match.group(1) if match else ""


def get_width_from_style(style):
    match = re.search(r'width:\s*([\d.]+)px', style)
    return match.group(1) if match else "0"


def get_height_from_style(style):
    match = re.search(r'height:\s*([\d.]+)px', style)
    return match.group(1) if match else "0"


def process_captcha():
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries:
        try:
            download_captcha_img()
            if check_captcha():
                logger.info("开始识别验证码")
                captcha = cv2.imread("temp/captcha.jpg")
                if captcha is None:
                    logger.error("无法读取验证码图片")
                    retry_count += 1
                    continue
                    
                with open("temp/captcha.jpg", 'rb') as f:
                    captcha_b = f.read()
                bboxes = det.detection(captcha_b)
                
                if not bboxes:
                    logger.error("未检测到验证码目标")
                    retry_count += 1
                    continue
                    
                result = dict()
                for i in range(len(bboxes)):
                    x1, y1, x2, y2 = bboxes[i]
                    spec = captcha[y1:y2, x1:x2]
                    cv2.imwrite(f"temp/spec_{i + 1}.jpg", spec)
                    
                    for j in range(3):
                        similarity, matched = compute_similarity(f"temp/sprite_{j + 1}.jpg", f"temp/spec_{i + 1}.jpg")
                        similarity_key = f"sprite_{j + 1}.similarity"
                        position_key = f"sprite_{j + 1}.position"
                        
                        if similarity_key in result.keys():
                            if float(result[similarity_key]) < similarity:
                                result[similarity_key] = similarity
                                result[position_key] = f"{int((x1 + x2) / 2)},{int((y1 + y2) / 2)}"
                        else:
                            result[similarity_key] = similarity
                            result[position_key] = f"{int((x1 + x2) / 2)},{int((y1 + y2) / 2)}"
                
                if check_answer(result):
                    for i in range(3):
                        similarity_key = f"sprite_{i + 1}.similarity"
                        position_key = f"sprite_{i + 1}.position"
                        
                        if position_key not in result:
                            continue
                            
                        position = result[position_key]
                        logger.info(f"图案 {i + 1} 位于 ({position})，匹配率：{result[similarity_key]}")
                        
                        try:
                            slideBg = wait.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="slideBg"]')))
                            style = slideBg.get_attribute("style")
                            x, y = int(position.split(",")[0]), int(position.split(",")[1])
                            width_raw, height_raw = captcha.shape[1], captcha.shape[0]
                            width, height = float(get_width_from_style(style)), float(get_height_from_style(style))
                            
                            if width > 0 and height > 0:
                                x_offset, y_offset = float(-width / 2), float(-height / 2)
                                final_x, final_y = int(x_offset + x / width_raw * width), int(y_offset + y / height_raw * height)
                                ActionChains(driver).move_to_element_with_offset(slideBg, final_x, final_y).click().perform()
                        except Exception as e:
                            logger.error(f"点击验证码位置失败: {str(e)}")
                            continue
                    
                    try:
                        confirm = wait.until(
                            EC.element_to_be_clickable((By.XPATH, '//*[@id="tcStatus"]/div[2]/div[2]/div/div')))
                        logger.info("提交验证码")
                        confirm.click()
                        time.sleep(5)
                        
                        result_elem = wait.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="tcOperation"]')))
                        if result_elem.get_attribute("class") == 'tc-opera pointer show-success':
                            logger.info("验证码通过")
                            return True
                        else:
                            logger.error("验证码未通过")
                    except TimeoutException:
                        logger.error("验证码提交后状态检查超时")
                else:
                    logger.error("验证码识别结果无效")
            else:
                logger.error("当前验证码识别率低，尝试刷新")
            
            # 刷新验证码
            try:
                reload = driver.find_element(By.XPATH, '//*[@id="reload"]')
                time.sleep(2)
                reload.click()
                time.sleep(3)
            except NoSuchElementException:
                logger.error("找不到验证码刷新按钮")
                break
                
            retry_count += 1
            
        except Exception as e:
            logger.error(f"处理验证码时发生错误: {str(e)}")
            retry_count += 1
            time.sleep(2)
    
    logger.error("验证码处理失败，已达到最大重试次数")
    return False


def download_captcha_img():
    try:
        if os.path.exists("temp"):
            for filename in os.listdir("temp"):
                file_path = os.path.join("temp", filename)
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.remove(file_path)
    except Exception as e:
        logger.error(f"清理临时文件失败: {str(e)}")
    
    try:
        slideBg = wait.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="slideBg"]')))
        img1_style = slideBg.get_attribute("style")
        img1_url = get_url_from_style(img1_style)
        
        if img1_url:
            logger.info("开始下载验证码图片(1): " + img1_url)
            download_image(img1_url, "captcha.jpg")
        else:
            logger.error("无法获取验证码图片1 URL")
            
        sprite = wait.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="instruction"]/div/img')))
        img2_url = sprite.get_attribute("src")
        
        if img2_url:
            logger.info("开始下载验证码图片(2): " + img2_url)
            download_image(img2_url, "sprite.jpg")
        else:
            logger.error("无法获取验证码图片2 URL")
            
    except TimeoutException:
        logger.error("获取验证码元素超时")
        raise


def check_captcha() -> bool:
    try:
        raw = cv2.imread("temp/sprite.jpg")
        if raw is None:
            logger.error("无法读取sprite图片")
            return False
            
        for i in range(3):
            w = raw.shape[1]
            temp = raw[:, w // 3 * i: w // 3 * (i + 1)]
            cv2.imwrite(f"temp/sprite_{i + 1}.jpg", temp)
            
            with open(f"temp/sprite_{i + 1}.jpg", mode="rb") as f:
                temp_rb = f.read()
            if ocr.classification(temp_rb) in ["0", "1"]:
                return False
        return True
    except Exception as e:
        logger.error(f"检查验证码时发生错误: {str(e)}")
        return False


def check_answer(d: dict) -> bool:
    try:
        if not d:
            return False
            
        flipped = dict()
        for key in d.keys():
            flipped[d[key]] = key
        return len(d.values()) == len(flipped.keys())
    except Exception as e:
        logger.error(f"检查答案时发生错误: {str(e)}")
        return False


def compute_similarity(img1_path, img2_path):
    try:
        img1 = cv2.imread(img1_path, cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imread(img2_path, cv2.IMREAD_GRAYSCALE)

        if img1 is None or img2 is None:
            return 0.0, 0

        sift = cv2.SIFT_create()
        kp1, des1 = sift.detectAndCompute(img1, None)
        kp2, des2 = sift.detectAndCompute(img2, None)

        if des1 is None or des2 is None:
            return 0.0, 0

        bf = cv2.BFMatcher()
        matches = bf.knnMatch(des1, des2, k=2)

        good = []
        for m_n in matches:
            if len(m_n) == 2:
                m, n = m_n
                if m.distance < 0.8 * n.distance:
                    good.append(m)

        if len(good) == 0:
            return 0.0, 0

        similarity = len(good) / len(matches) if matches else 0
        return similarity, len(good)
    except Exception as e:
        logger.error(f"计算相似度时发生错误: {str(e)}")
        return 0.0, 0


if __name__ == "__main__":
    # 基础配置
    timeout = 25  # 单次操作超时时间
    max_delay = 90
    user = os.environ.get('RAINYUN_USER', 'username')
    pwd = os.environ.get('RAINYUN_PASSWD', '12345678')
    
    # 警告默认凭据
    if user == 'username' or pwd == '12345678':
        logging.warning("警告：正在使用默认的用户名或密码，请在环境变量中设置 RAINYUN_USER 和 RAINYUN_PWD！")
    
    debug = True
    linux = True

    # 日志配置
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)
    ver = "2.3"
    
    logger.info("------------------------------------------------------------------")
    logger.info(f"雨云签到工具 v{ver} by SerendipityR ~")
    logger.info("Github发布页: https://github.com/SerendipityR-2022/Rainyun-Qiandao")
    logger.info("------------------------------------------------------------------")
    logger.info("-----------本项目为二开封装Docker运行方式原作者在上面-------------")
    logger.info("                   交流Q群：5036150 欢迎加入 ~                    ")
    
    # 网络检查
    if not check_network():
        logger.warning("网络连接检查失败，等待网络恢复...")
        time.sleep(30)
    
    # 随机延时
    delay = random.randint(0, max_delay)
    delay_sec = random.randint(0, 60)
    if not debug:
        logger.info(f"随机延时等待 {delay} 分钟 {delay_sec} 秒")
        time.sleep(delay * 60 + delay_sec)
    
    # 初始化OCR
    logger.info("初始化 ddddocr")
    try:
        ocr = ddddocr.DdddOcr(ocr=True, show_ad=False)
        det = ddddocr.DdddOcr(det=True, show_ad=False)
    except Exception as e:
        logger.error(f"OCR初始化失败: {str(e)}")
        exit(1)
    
    # 初始化Selenium
    logger.info("初始化 Selenium")
    try:
        driver = init_selenium()
    except Exception as e:
        logger.error(f"Selenium初始化失败: {str(e)}")
        exit(1)
    
    # 反检测脚本
    try:
        with open("stealth.min.js", mode="r") as f:
            js = f.read()
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": js
        })
    except FileNotFoundError:
        logger.warning("未找到stealth.min.js文件，跳过反检测脚本")
    except Exception as e:
        logger.warning(f"执行反检测脚本失败: {str(e)}")
    
    # 登录流程
    login_success = False
    max_login_retries = 3
    
    for login_attempt in range(max_login_retries):
        try:
            logger.info(f"第 {login_attempt + 1} 次登录尝试")
            driver.set_page_load_timeout(timeout)
            
            # 先访问主页测试
            driver.get("https://app.rainyun.com/")
            time.sleep(2)
            
            # 访问登录页
            driver.get("https://app.rainyun.com/auth/login")
            
            wait = WebDriverWait(driver, timeout)
            
            # 查找登录元素
            username = wait.until(EC.presence_of_element_located((By.NAME, 'login-field')))
            password = wait.until(EC.presence_of_element_located((By.NAME, 'login-password')))
            login_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[@type="submit"]')))
            
            # 输入登录信息
            username.clear()
            username.send_keys(user)
            password.clear()
            password.send_keys(pwd)
            login_button.click()
            
            logger.info("登录信息已提交")
            time.sleep(5)
            
            # 检查登录结果
            if "dashboard" in driver.current_url:
                logger.info("登录成功！")
                login_success = True
                break
            elif "tcaptcha" in driver.page_source or "tcaptcha_iframe_dy" in driver.page_source:
                logger.warning("触发验证码！")
                driver.switch_to.frame("tcaptcha_iframe_dy")
                if process_captcha():
                    driver.switch_to.default_content()
                    if "dashboard" in driver.current_url:
                        logger.info("登录成功！")
                        login_success = True
                        break
                else:
                    driver.switch_to.default_content()
                    logger.error("验证码处理失败")
            else:
                logger.error("登录状态未知")
                
        except TimeoutException:
            logger.warning(f"第 {login_attempt + 1} 次登录超时")
            if login_attempt < max_login_retries - 1:
                time.sleep(10)
                continue
        except Exception as e:
            logger.error(f"第 {login_attempt + 1} 次登录失败: {str(e)}")
            if login_attempt < max_login_retries - 1:
                time.sleep(10)
                continue
    
    if not login_success:
        logger.error("所有登录尝试均失败")
        driver.quit()
        exit(1)
    
    # 执行签到任务
    try:
        logger.info("正在转到赚取积分页")
        driver.get("https://app.rainyun.com/account/reward/earn")
        driver.implicitly_wait(10)
        
        # 查找赚取积分按钮
        try:
            earn = wait.until(EC.element_to_be_clickable((By.XPATH,
                               '//a[contains(@class, "btn") and contains(text(), "赚取积分")]')))
            logger.info("点击赚取积分")
            earn.click()
        except:
            # 备用定位方式
            earn_links = driver.find_elements(By.XPATH, '//a[contains(text(), "赚取积分")]')
            if earn_links:
                earn_links[0].click()
                logger.info("点击赚取积分（备用方式）")
            else:
                logger.warning("未找到赚取积分按钮，可能已经在该页面")
        
        logger.info("处理验证码")
        driver.switch_to.frame("tcaptcha_iframe_dy")
        process_captcha()
        driver.switch_to.default_content()
        
        # 获取积分信息
        driver.implicitly_wait(10)
        try:
            points_element = wait.until(EC.visibility_of_element_located((By.XPATH,
                '//h3[contains(@class, "points") or contains(text(), "积分")]')))
            points_raw = points_element.get_attribute("textContent")
            current_points = int(''.join(re.findall(r'\d+', points_raw))) if points_raw else 0
            logger.info(f"当前剩余积分: {current_points} | 约为 {current_points / 2000:.2f} 元")
        except:
            logger.warning("无法获取积分信息")
        
        logger.info("任务执行成功！")
        
    except Exception as e:
        logger.error(f"执行签到任务时发生错误: {str(e)}")
    finally:
        driver.quit()
        logger.info("浏览器已关闭")
