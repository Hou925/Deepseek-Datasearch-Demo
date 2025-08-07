import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE")
    )

def search_housing(
    keyword=None,
    city=None,
    min_price=None,
    max_price=None,
    top_k=5
):
    """
    更友好的房源检索方法
    :param keyword: 任意关键词（支持标题、描述、地址模糊）
    :param city: 城市名（模糊匹配）
    :param min_price: 最低租金（可选）
    :param max_price: 最高租金（可选）
    :param top_k: 返回条数
    :return: list[dict]
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    conditions = []
    params = []

    # 关键词模糊检索
    if keyword and keyword.strip() != "":
        kw = f"%{keyword.strip()}%"
        conditions.append(
            "(title LIKE %s OR description LIKE %s OR address LIKE %s)"
        )
        params.extend([kw, kw, kw])
    else:
        conditions.append("1=1")  # 无关键词时不过滤

    # 城市模糊匹配
    if city and city.strip() != "":
        ct = f"%{city.strip()}%"
        conditions.append("city LIKE %s")
        params.append(ct)

    # 价格区间
    if min_price is not None and str(min_price).strip() != "":
        try:
            min_price = int(min_price)
            conditions.append("price >= %s")
            params.append(min_price)
        except Exception:
            pass
    if max_price is not None and str(max_price).strip() != "":
        try:
            max_price = int(max_price)
            conditions.append("price <= %s")
            params.append(max_price)
        except Exception:
            pass

    # 拼接SQL
    where_sql = " AND ".join(conditions)
    sql = f"""
        SELECT id, title, address, city, district, price, area,
               bedrooms, bathrooms, floor, orientation, description,
               contact, updated_at
        FROM housing
        WHERE {where_sql}
        ORDER BY updated_at DESC
        LIMIT %s
    """
    params.append(top_k)

    print("【SQL调试】", sql)
    print("【参数】", params)

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows