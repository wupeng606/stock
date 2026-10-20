#!/usr/bin/env python3
# old name: get_backward_adjusted_daily_stock_v3.py

import chinese_calendar
import datetime
import json
import logging
import random
import re
import sqlite3
import sys
import time

import numpy
import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from environs import Env


class StockDataProcessor:
    def __init__(self):
        self.env = Env()
        self.env.read_env('default.env')
        self.db_path = self.env.str("DB_PATH")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )
        self.init_database()
        self.start_time = datetime.datetime.now(datetime.UTC)

        logging.basicConfig(
            #level=logging.CRITICAL,
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s"

        )
        self.logger = logging.getLogger("my_logger")
        # self.logger.addHandler(logging.StreamHandler())
        self.is_download_forced = True

    def init_database(self):
        """初始化数据库表结构"""
        with sqlite3.connect(self.db_path) as conn:
            # 创建分红送股数据表
            conn.execute("""
                    CREATE TABLE IF NOT EXISTS stock_dividends (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        declare_date TEXT,
                        ex_dividend_date TEXT,
                        cash_dividend_per_share REAL,
                        bonus_share_ratio REAL,
                        capital_share_ratio REAL,
                        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, declare_date)
                    )
                """)

            # 创建日线数据表
            conn.execute("""
                    CREATE TABLE IF NOT EXISTS stock_daily (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume REAL,
                        amount REAL,
                        NHNL50 REAL,    /* New High - New Low for 50 days */
                        NHNL120 REAL,
                        NHNL242 REAL,
                        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, trade_date)
                    )
                """)

            # 创建前复权数据表
            conn.execute("""
                    CREATE TABLE IF NOT EXISTS stock_adjusted (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        adj_open REAL,
                        adj_high REAL,
                        adj_low REAL,
                        adj_close REAL,
                        adj_volume REAL,
                        amount REAL,
                        adjust_factor REAL,
                        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, trade_date)
                    )
                """)

            # 创建基础数据表
            conn.execute("""
                    CREATE TABLE IF NOT EXISTS stock_basics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        name TEXT NOT NULL,
                        pe REAL,             /*市盈率          */
                        pe_ttm REAL,         /*市盈率（动态）          */
                        pe_lyr REAL,         /*市盈率（静态）          */
                        pb REAL,             /*市净率          */
                        ps REAL,             /*市销率          */
                        pcf REAL,            /*市现率          */
                        eps REAL,            /*每股收益          */
                        total_mv REAL,       /*总市值          */
                        float_mv REAL,       /*流通市值          */
                        total_share REAL,    /*总股本          */
                        float_share REAL,    /*流通股本          */
                        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, date)
                    )
                """)

            # 创建日线数据表
            conn.execute("""
                    CREATE TABLE IF NOT EXISTS stock_index (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_date TEXT NOT NULL,
                        NHNL50 REAL,
                        NHNL120 REAL,
                        NHNL242 REAL,
                        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(trade_date)
                    )
                """)

    def get_dividend_data(self, symbol):
        pure_symbol = symbol[2:] if symbol.startswith(("sh", "sz")) else symbol
        # logger.debug('Starts timming: {}'.format(datetime.datetime.now(datetime.UTC) - self.start_time ))

        """获取单只股票的分红数据"""
        url = f"{self.env.str("DIVIDEND_LINK_PREFIX")}{pure_symbol}{self.env.str("DIVIDEND_LINK_APPENDIX")}"

        self.logger.info(
            "Debug: create chrome options. {}".format(
                datetime.datetime.now(datetime.UTC) - self.start_time
            )
        )

        chrome_options = webdriver.ChromeOptions()
        chrome_options.page_load_strategy = "eager"
        chrome_options.add_argument("user-data-dir=./chrome_cust_profile")
        # chrome_options.add_argument("disk-cache-dir=./chrome_cache")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-extensions")
        # chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")
        chrome_options.add_argument("--disable-notifications")
        # chrome_options.add_argument('--disable-background-networking')
        chrome_options.add_argument('--headless')
        chrome_options.binary_location = (
            self.env.str("CHROME_BINARY_LOCATION")
        )

        # driver.set_page_load_timeout(180)
        service = Service(
            #executable_path=f'{self.env.str("CHROME_BINARY_LOCATION")}/chromedrive'
            # TODO : can not use env for now, need to fix
            executable_path="/home/frank/opt/chrome/chrome-current/chromedriver-linux64/chromedriver"
        )

        try:
            self.logger.info(
                "Debug: creating webdriver.{}".format(
                    datetime.datetime.now(datetime.UTC) - self.start_time
                )
            )
            driver = webdriver.Chrome(options=chrome_options, service=service)

            self.logger.info("Debug: Driver getting url: {}".format(url))
            driver.get(url)
            self.logger.info("Debug: Driver getting url finished.")
            # WebDriverWait(driver,120,1).until(ex.visibility_of_element_located((By.XPATH, '//*[@id="sharebonus_1"]')))
            soup = BeautifulSoup(driver.page_source, "lxml")
            # logger.debug('Debug: Getting soup.{}'.format(datetime.datetime.now(datetime.UTC) - self.start_time ))
            # response = requests.get(url, headers=headers)
            # soup = BeautifulSoup(response.text, 'html.parser')
            table = soup.find("table", {"id": "sharebonus_1"})
            # logger.debug('Debug: Searching table.{}'.format(datetime.datetime.now(datetime.UTC) - self.start_time ))
            tbody = table.find("tbody")

            dividends = []
            # for row in table.find_all('tr')[1:]:  # 跳过表头
            for row in tbody.find_all("tr"):
                cols = [col.get_text(strip=True) for col in row.find_all("td")]
                if len(cols) >= 6:
                    try:
                        #'symbol': symbol,
                        declare_date = cols[0]
                        bonus_share_ratio = float(cols[1]) / 10
                        capital_share_ratio = float(cols[2]) / 10
                        cash_dividend_per_share = float(cols[3]) / 10
                        progress = cols[4]
                        record_date = cols[6]
                        ex_dividend_date = cols[5]

                        # 只添加有实际分红或送转的数据
                        if (
                            bonus_share_ratio > 0
                            or capital_share_ratio > 0
                            or cash_dividend_per_share > 0
                        ):
                            dividends.append(
                                {
                                    "symbol": symbol,
                                    "declare_date": declare_date,
                                    "bonus_share_ratio": bonus_share_ratio,
                                    "capital_share_ratio": capital_share_ratio,
                                    "cash_dividend_per_share": cash_dividend_per_share,
                                    "progress": progress,
                                    "record_date": record_date,
                                    "ex_dividend_date": ex_dividend_date,
                                }
                            )
                    except Exception as e:
                        print(f"解析分红数据时出错: {e}")
                        continue

            # logger.debug('Debug: closing webdriver instance at: {}'.format(datetime.datetime.now(datetime.UTC) - self.start_time ))
            time.sleep(3)
            self.logger.debug("dividends : {}".format(dividends))
            return dividends
        except Exception as e:
            print(f"获取{symbol}分红数据失败: {str(e)}")
            return []
        finally:
            driver.close()
            driver.quit()

    def save_dividends_to_db(self, symbol: str, dividends: list):

        with sqlite3.connect(self.db_path) as conn:
            for dividend in dividends:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO stock_dividends
                    (symbol, declare_date, ex_dividend_date, cash_dividend_per_share, bonus_share_ratio, capital_share_ratio)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        dividend["symbol"],
                        dividend["declare_date"],
                        dividend["ex_dividend_date"],
                        dividend["cash_dividend_per_share"],
                        dividend["bonus_share_ratio"],
                        dividend["capital_share_ratio"],
                    ),
                )
            #print(f"数据已保存到 DB: {self.db_path}")

    def get_daily_data(self, symbol: str, scale: int = 240, datalen: int = 2000) -> pd.DataFrame:
        """
        从新浪财经获取日线数据
        symbol: 股票代码，如 'sh600000'
        scale: 240表示日线，60表示60分钟线等
        datalen: 获取的数据长度
        """
        #url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        url = self.env.str("DAILY_LINK")
        params = {"symbol": symbol, "scale": scale, "datalen": datalen, "ma": "no"}

        try:
            # response = self.session.get(url, params=params, timeout=10)
            response = requests.get(url, params=params, timeout=10)
            self.logger.debug("session text: {}".format(response.text))
            # 处理可能的非JSON响应
            if response.text.startswith("["):
                data = json.loads(response.text)
            else:
                print(f"获取数据失败: {response.text}")
                return pd.DataFrame()

            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)

            # 转换数据类型
            df["day"] = pd.to_datetime(df["day"])
            df["open"] = pd.to_numeric(df["open"])
            df["high"] = pd.to_numeric(df["high"])
            df["low"] = pd.to_numeric(df["low"])
            df["close"] = pd.to_numeric(df["close"])
            df["volume"] = pd.to_numeric(df["volume"])

            # 重命名列
            df = df.rename(columns={"day": "trade_date"})

            # 添加股票代码
            df["symbol"] = symbol

            # 按日期升序排列
            df = df.sort_values("trade_date").reset_index(drop=True)

            return df

        except Exception as e:
            print(f"获取日线数据失败: {e}")
            return pd.DataFrame()

    def get_today_data(self, symbol: str, scale: int = 5, datalen: int = 48) -> pd.DataFrame:
        """
        从新浪财经获取日线数据
        symbol: 股票代码，如 'sh600000'
        scale: 240表示日线，60表示60分钟线等
        datalen: 获取的数据长度
        """
        try:
            #url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
            url = self.env.str("DAILY_LINK")
            params = {"symbol": symbol, "scale": scale, "datalen": datalen, "ma": "no"}
            # response = self.session.get(url, params=params, timeout=10)
            response = requests.get(url, params=params, timeout=10)
            self.logger.debug("session text: {}".format(response.text))
            # 处理可能的非JSON响应
            if response.text.startswith("["):
                data = json.loads(response.text)
            else:
                print(f"获取数据失败: {response.text}")
                return pd.DataFrame()

            if not data:
                return pd.DataFrame()

            today_date = datetime.date.today().strftime("%Y-%m-%d")
            df = pd.DataFrame(data)

            # 转换数据类型
            # df['day'] = pd.to_datetime(df['day'])
            df["open"] = pd.to_numeric(df["open"])
            df["high"] = pd.to_numeric(df["high"])
            df["low"] = pd.to_numeric(df["low"])
            df["close"] = pd.to_numeric(df["close"])
            df["volume"] = pd.to_numeric(df["volume"])

            # 重命名列
            df = df.rename(columns={"day": "trade_date"})

            df["symbol"] = symbol

            df1 = df[df["day"].str.contains(today_date)]

            # 按日期升序排列
            df2 = df1.sort_values("trade_date").reset_index(drop=True)

            open = df2.iloc[0, 1]
            high = df2["high"].max()
            low = df2["low"].min()
            close = df2.iloc[len(df2) - 1, 4]
            volume = df2["volume"].sum()

            new_df = pd.DataFrame(
                [
                    {
                        "trade_date": today_date,
                        "open": open,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    }
                ]
            )
            new_df["trade_date"] = pd.to_datetime(new_df["trade_date"])

            return new_df
        except Exception as e:
            print(f"获取数据失败: {e}")
            return pd.DataFrame()

    def save_daily_data_to_db(self, df: pd.DataFrame):
        """保存日线数据到数据库"""
        if df.empty:
            return

        with sqlite3.connect(self.db_path) as conn:
            for _, row in df.iterrows():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO stock_daily
                    (symbol, trade_date, open, high, low, close, volume, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        row["symbol"],
                        row["trade_date"].strftime("%Y-%m-%d"),
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row.get("volume", 0),
                        row.get("amount", 0),
                    ),
                )

    def calculate_backward_adjustment(self, symbol: str) -> pd.DataFrame:
        """
        计算前复权价格（从后向前复权）
        前复权：保持最新价格不变，向前调整历史价格
        """
        # 从数据库获取日线数据和分红数据
        with sqlite3.connect(self.db_path) as conn:
            daily_df = pd.read_sql(
                """
                SELECT * FROM stock_daily
                WHERE symbol = ?
                ORDER BY trade_date
            """,
                conn,
                params=[symbol],
            )

            dividends_df = pd.read_sql(
                """
                SELECT * FROM stock_dividends
                WHERE symbol = ? and ex_dividend_date LIKE '____-__-__'
                ORDER BY ex_dividend_date
            """,
                conn,
                params=[symbol],
            )

        if daily_df.empty:
            print("没有找到日线数据")
            return pd.DataFrame()

        # 转换日期格式
        daily_df["trade_date"] = pd.to_datetime(daily_df["trade_date"])
        dividends_df["ex_dividend_date"] = pd.to_datetime(
            dividends_df["ex_dividend_date"]
        )

        # 初始化复权因子为1
        daily_df["adjust_factor"] = 1.0

        # 按除权除息日倒序处理（从最近到最早）
        for _, dividend in dividends_df.sort_values(
            "ex_dividend_date", ascending=False
        ).iterrows():
            ex_date = dividend["ex_dividend_date"]
            cash_dividend_per_share = dividend["cash_dividend_per_share"] or 0
            bonus_share_ratio = dividend["bonus_share_ratio"] or 0
            capital_share_ratio = dividend["capital_share_ratio"] or 0

            # 计算总送转比例
            total_share_ratio = bonus_share_ratio + capital_share_ratio

            # 找到除权除息日前一天的记录
            prev_day_mask = daily_df["trade_date"] < ex_date
            if not daily_df[prev_day_mask].empty:
                # 获取除权除息日前一天的收盘价
                prev_close = daily_df[prev_day_mask].iloc[-1]["close"]

                # 计算理论前复权价格（除权除息日前一天的价格调整后应该等于的理论价格）
                # 前复权价格 = (当日收盘价 - 每股分红) / (1 + 送股比例 + 转增比例)
                theoretical_price = (prev_close - cash_dividend_per_share) / (
                    1 + total_share_ratio
                )

                # 计算调整因子
                adjust_factor = theoretical_price / prev_close

                # 应用调整因子到除权除息日之前的所有数据
                mask = daily_df["trade_date"] < ex_date
                daily_df.loc[mask, "adjust_factor"] *= adjust_factor

        # 计算前复权价格
        daily_df["adj_open"] = round(daily_df["open"] * daily_df["adjust_factor"], 2)
        daily_df["adj_high"] = round(daily_df["high"] * daily_df["adjust_factor"], 2)
        daily_df["adj_low"] = round(daily_df["low"] * daily_df["adjust_factor"], 2)
        daily_df["adj_close"] = round(daily_df["close"] * daily_df["adjust_factor"], 2)
        daily_df["adj_volume"] = round(daily_df["volume"] / daily_df["adjust_factor"], 2)

        return daily_df

    def save_adjusted_data_to_db(self, adjusted_df: pd.DataFrame):
        """保存前复权数据到数据库"""
        if adjusted_df.empty:
            return

        with sqlite3.connect(self.db_path) as conn:
            for _, row in adjusted_df.iterrows():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO stock_adjusted
                    (symbol, trade_date, adj_open, adj_high, adj_low, adj_close, adj_volume, adjust_factor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        row["symbol"],
                        row["trade_date"].strftime("%Y-%m-%d"),
                        row["adj_open"],
                        row["adj_high"],
                        row["adj_low"],
                        row["adj_close"],
                        row["adj_volume"],
                        row["adjust_factor"],
                    ),
                )

    def process_stock_data(self, symbol: str, datalen: int = 1000):
        """
        完整的股票数据处理流程
        """
        print(f"\n开始处理股票 {symbol} 的数据...")

        # 提取纯数字代码用于分红数据获取
        # pure_symbol = symbol[2:] if symbol.startswith(('sh', 'sz')) else symbol

        # 0. Check if the data was download already
        #is_download_forced = True
        if self.check_data_downloaded2(symbol):
            print(f"Data was processed for {symbol}. Skipping for this time.")
            return pd.DataFrame()

        # 1. 获取并保存分红送股信息
        print("1. 获取分红送股信息...")
        dividends = self.get_dividend_data(symbol)
        if dividends:
            self.save_dividends_to_db(symbol, dividends)
            #print(f"成功保存 {len(dividends)} 条分红记录")
        else:
            #print("未获取到分红信息, 将跳过后续步骤.")
            #return
            pass # 临时为了打到的新股

        # 2. 获取并保存日线数据
        print("2. 获取日线数据...")
        daily_data = self.get_daily_data(symbol, datalen=datalen)
        if not daily_data.empty:
            self.save_daily_data_to_db(daily_data)
            #print(f"成功保存 {len(daily_data)} 条日线记录")
        else:
            print("未获取到日线数据")
            return pd.DataFrame()

        # 3. 计算前复权数据
        print("3. 计算前复权数据...")
        adjusted_data = self.calculate_backward_adjustment(symbol)
        if not adjusted_data.empty:
            self.save_adjusted_data_to_db(adjusted_data)
            #print(f"成功计算并保存 {len(adjusted_data)} 条前复权记录")

            # 4. 输出前复权数据
            print("4. 前复权数据示例 (最新100个交易日):")
            result_df = adjusted_data[
                [
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "adj_open",
                    "adj_high",
                    "adj_low",
                    "adj_close",
                    "adjust_factor",
                ]
            ].tail(100)
            #print(result_df.round(3))
            print('略')

            return adjusted_data
        else:
            print("计算前复权数据失败")
            return pd.DataFrame()

    def export_adjusted_data(self, symbol: str, output_file: str = None):
        """导出前复权数据到CSV文件"""
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql(
                """
                SELECT trade_date, adj_open as open, adj_high as high, adj_low as low,
                       adj_close as close, adj_volume, adjust_factor
                FROM stock_adjusted
                WHERE symbol = ?
                ORDER BY trade_date
            """,
                conn,
                params=[symbol],
            )

        if not df.empty:
            if output_file:
                df.to_csv(output_file, index=False)
                print(f"前复权数据已导出到: {output_file}")
            return df
        else:
            print("没有找到前复权数据")
            return pd.DataFrame()

    def check_data_downloaded(self, symbol: str):
        # Get Lastest trade data date for the symbol.
        with sqlite3.connect(self.db_path) as conn:
            df_local = pd.read_sql(
                """
                SELECT
                    max(trade_date) as trade_date
                FROM stock_adjusted
                WHERE symbol = ?
                """,
                conn,
                params=[symbol],
            )
        if df_local.empty:
            return False
        df_local["trade_date"] = pd.to_datetime(df_local["trade_date"])

        url = self.env.str("DAILY_LINK")
        params = {"symbol": symbol, "scale": 240, "datalen": 3, "ma": "no"}
        try:
            response = requests.get(url, params=params, timeout=10)
            # 处理可能的非JSON响应
            if response.text.startswith("["):
                data = json.loads(response.text)
            else:
                return False

            if not data:
                return False

            df_online = pd.DataFrame(data)
            df_online["day"] = pd.to_datetime(df_online["day"])
            df_online = df_online.rename(columns={"day": "trade_date"})
        except Exception as e:
            print(f"Failed to check online data: {e}")
            sys.exit()

        return df_local.iloc[0, 0] == df_online["trade_date"].max()

    def check_data_downloaded2(self, symbol: str):
        last_trade_day = self.get_last_tradeday()
        with sqlite3.connect(self.db_path) as conn:
            sql =  "SELECT * FROM stock_adjusted WHERE symbol = '{}' and trade_date = '{}' ".format(symbol, last_trade_day)
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
        if self.is_download_forced is True:
            return False
        return len(rows) > 0


    def get_symbols_downloaded(self):
        last_trade_day = self.get_last_tradeday()
        with sqlite3.connect(self.db_path) as conn:
            sql =  "SELECT symbol FROM stock_adjusted WHERE trade_date = '{}' ".format(last_trade_day)
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
        #conn.close()
        return [_[0] for _ in rows]

    # get last trade day before today
    def get_last_tradeday(self):
        today_date = datetime.date.today()
        yesterday_date = today_date - datetime.timedelta(days=1)
        start_date = today_date - datetime.timedelta(days=15)

        #start = datetime.datetime.strptime(start_str, "%Y-%m-%d").date()
        #end = datetime.datetime.strptime(end_str, "%Y-%m-%d").date()
        lst = chinese_calendar.get_workdays(start_date, yesterday_date)
        expt = []
        for d in lst:
            if d.isoweekday() == 6 or d.isoweekday() == 7:
                expt.append(d)
        for d in expt:
            lst.remove(d)
        date_list = [item.strftime("%Y-%m-%d") for item in lst]
        return date_list[-1]

def get_extensive_symbols(db_path: str, pe_low=0, pe_high=30, total_mv_low=100, total_mv_high=100_000, pb_high=3):
    #db_path = "/home/frank/peng/lab/quant_trading/download_data/stock.db"
    with sqlite3.connect(db_path) as conn:
        sql =  """SELECT symbol
            FROM stock_basics
            WHERE pe > {} and pe < {} and total_mv > {} and total_mv < {} and float_mv/total_mv > 0.9 and pb <{};
        """.format(pe_low, pe_high, total_mv_low, total_mv_high, pb_high)
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
    conn.close()
    return [_[0] for _ in rows]

def main():
    env = Env()
    env.read_env('default.env')
    #db_path=env.str("DB_PATH")      #"/mnt/ramdisk/stock.db"
    processor = StockDataProcessor()
    symbols=env.list("SYMBOLS")
    zero_dividend_symbols=env.list("ZERO_DIVIDEND_SYMBOLS")

    extensive_symbols = get_extensive_symbols(db_path=env.str("DB_PATH"))
    extensive_symbols = []
    all_symbols = list(set(symbols + extensive_symbols))
    downloaded_symbols = set(processor.get_symbols_downloaded())
    result_symbols = [ _ for _ in all_symbols if _ not in downloaded_symbols and _ not in zero_dividend_symbols]
    print(f'Number of all symbols: {len(all_symbols)}; Downloaded: {len(downloaded_symbols)}; To do: {len(result_symbols)}')

    if len(sys.argv) >= 2:
        result_symbols = []
        for i in range(1, len(sys.argv)):
            if re.match(r"^(sh|sz)[0-9]{6}$", str(sys.argv[i])):
                result_symbols.append(str(sys.argv[i]))
                # print(f'appended: {sys.argv[i]}')
            else:
                print("****This code is wrong: %s ****" % sys.argv[i])

    cnt = len(result_symbols)
    # 执行完整的数据处理流程
    for symbol in result_symbols:
        if processor.check_data_downloaded2(symbol):
            print(f"Data downloaded for {symbol}, jumping to next symbol.")
            continue
        result = processor.process_stock_data(symbol, datalen=500)
        # 显示数据统计
        if result is not None and not result.empty:
            print("数据统计:")
            print(f"  处理时间范围: {result['trade_date'].min()} 到 {result['trade_date'].max()}")
            print(f"  总交易天数: {len(result)}")
            print(f"  最新前复权收盘价: {result['adj_close'].iloc[-1]:.2f}")
            #print(f"  最新复权因子: {result['adjust_factor'].iloc[-1]:.6f}")
            # 导出数据
            # processor.export_adjusted_data(symbol, f"{symbol}_forward_adjusted.csv")
        # res=processor.get_stock_basics(symbol=symbol)
        # processor.save_stock_basics_to_db(data=res)
        cnt -= 1
        if cnt != 0:
            print(f'Symbols to process： {cnt}')
            time.sleep(random.uniform(2, 5))  # 随机延时避免反爬


if __name__ == "__main__":
    main()
