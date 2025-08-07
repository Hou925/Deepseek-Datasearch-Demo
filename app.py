from flask import Flask, request, jsonify
from flask_cors import CORS
from db import search_housing
from deepseek import deepseek_chat
import re

app = Flask(__name__)
CORS(app)

def housing_list_to_markdown(house_list):
    """将房源列表格式化为Markdown表格"""
    if not house_list:
        return "无匹配房源。"
    headers = ["编号", "标题", "城市", "区域", "价格", "面积", "卧室数", "楼层", "朝向", "描述"]
    lines = ["| " + " | ".join(headers) + " |", 
             "| " + " | ".join(['---'] * len(headers)) + " |"]
    for idx, h in enumerate(house_list, 1):
        line = [
            str(idx),
            h.get("title", ""),
            h.get("city", ""),
            h.get("district", ""),
            str(h.get("price", "")),
            str(h.get("area", "")),
            str(h.get("bedrooms", "")),
            str(h.get("floor", "")),
            h.get("orientation", ""),
            (h.get("description", "") or "")[:20]  # 描述只显示前20字，避免太长
        ]
        lines.append("| " + " | ".join(line) + " |")
    return "\n".join(lines)

def build_prompt(house_list, user_query):
    sys_msg = {
        "role": "system",
        "content": (
            "你是一个房产助手。请只根据以下本地房源数据回答用户问题，不要编造信息，如果没有合适的房源，请回复'没有找到符合条件的房源'。本地房源数据如下："
        )
    }
    if house_list:
        doc_msg = {
            "role": "system",
            "content": (
                "以下为本地住房信息检索结果（表格）：\n"
                + housing_list_to_markdown(house_list)
            )
        }
        messages = [sys_msg, doc_msg]
    else:
        messages = [sys_msg]
    messages.append({"role": "user", "content": user_query})
    return messages

def smart_extract_keywords(query):
    """
    智能提取用户查询中的各类房产相关信息
    返回一个字典，包含可能的城市、朝向、价格范围、房型等信息
    """
    result = {
        "city": None,
        "orientation": None,
        "min_price": None,
        "max_price": None,
        "keywords": []
    }
    
    # 城市匹配（可扩展更多城市）
    cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "重庆", "武汉", "西安", 
              "天津", "苏州", "厦门", "长沙", "青岛", "大连", "宁波", "郑州"]
    for city in cities:
        if city in query:
            result["city"] = city
            # 从查询中移除城市名，避免重复检索
            query = query.replace(city, " ")
            break
    
    # 朝向匹配
    orientations = ["朝南", "朝北", "朝东", "朝西", "南北通透", "东西向", "南向", "北向", "东向", "西向"]
    for orientation in orientations:
        if orientation in query:
            result["orientation"] = orientation.replace("朝", "").replace("向", "")
            query = query.replace(orientation, " ")
            break
    
    # 价格范围匹配
    price_pattern = r'(\d+)(?:元|块|万|k|K)?(?:以[下内]|以[上外]|左右)'
    price_matches = re.findall(price_pattern, query)
    if price_matches:
        if "以下" in query or "以内" in query:
            result["max_price"] = int(price_matches[0])
        elif "以上" in query or "以外" in query:
            result["min_price"] = int(price_matches[0])
        # 处理价格区间，如"3000到5000"
        price_range = re.search(r'(\d+)(?:元|块|万)?\s*(?:到|至|~|-)\s*(\d+)(?:元|块|万)?', query)
        if price_range:
            result["min_price"] = int(price_range.group(1))
            result["max_price"] = int(price_range.group(2))
    
    # 提取其他关键词
    # 先移除已匹配的特定条件
    query = re.sub(price_pattern, " ", query)
    
    # 常见房产相关词汇（可以扩展）
    property_terms = ["公寓", "住宅", "小区", "楼盘", "花园", "广场", "新房", "二手房", 
                      "复式", "单身公寓", "一室", "两室", "三室", "四室", "多室", 
                      "一厅", "两厅", "大厅", "卧室", "客厅", "洗手间", "卫生间", "厨房",
                      "电梯", "地铁", "学区", "学校", "公园", "医院", "商场", "超市",
                      "精装", "豪装", "简装", "毛坯", "家具", "家电", "拎包入住"]
    
    # 提取可能的房产相关词汇
    for term in property_terms:
        if term in query:
            result["keywords"].append(term)
            query = query.replace(term, " ")
    
    # 分词提取剩余可能的关键词
    remaining_words = re.split(r'[\s,，.。:：;；!！?？]+', query)
    for word in remaining_words:
        if len(word) >= 2 and word not in result["keywords"]:
            result["keywords"].append(word)
    
    return result

@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.get_json()
    # 兼容前端传参
    query = data.get("query", "") or data.get("question", "")  # 支持 question/query 字段
    city = data.get("city")
    min_price = data.get("min_price")
    max_price = data.get("max_price")
    top_k = data.get("top_k", 5)

    # 类型转换健壮处理
    try:
        min_price = int(min_price) if min_price not in (None, "") else None
    except Exception:
        min_price = None
    try:
        max_price = int(max_price) if max_price not in (None, "") else None
    except Exception:
        max_price = None
    try:
        top_k = int(top_k)
    except Exception:
        top_k = 5
        
    # 智能关键词提取
    extracted_info = smart_extract_keywords(query)
    print("【提取信息】", extracted_info)  # 调试用
    
    # 使用提取的信息覆盖前端传入的值（如果前端未指定）
    if not city and extracted_info["city"]:
        city = extracted_info["city"]
    if min_price is None and extracted_info["min_price"]:
        min_price = extracted_info["min_price"]
    if max_price is None and extracted_info["max_price"]:
        max_price = extracted_info["max_price"]
    
    # 构建智能关键词字符串
    search_keywords = []
    if extracted_info["orientation"]:
        search_keywords.append(extracted_info["orientation"])
    search_keywords.extend(extracted_info["keywords"])
    smart_keyword = " ".join(search_keywords)
    
    # 使用智能提取的关键词进行搜索
    housing_docs = search_housing(
        keyword=smart_keyword,
        city=city,
        min_price=min_price,
        max_price=max_price,
        top_k=top_k
    )
    
    # 如果没有结果，尝试使用单个关键词搜索
    if not housing_docs and extracted_info["keywords"]:
        for keyword in extracted_info["keywords"]:
            results = search_housing(
                keyword=keyword,
                city=city,
                min_price=min_price,
                max_price=max_price,
                top_k=top_k
            )
            if results:
                housing_docs = results
                break
    
    # 如果仍然没有结果，尝试只用城市搜索
    if not housing_docs and city:
        housing_docs = search_housing(
            keyword="",
            city=city,
            min_price=min_price,
            max_price=max_price,
            top_k=top_k
        )
    
    # 如果依然没有结果，尝试使用原始查询做一次最后的尝试
    if not housing_docs:
        housing_docs = search_housing(
            keyword=query,
            city=None,
            min_price=None,
            max_price=None,
            top_k=top_k
        )

    print("【检索到的房源】", housing_docs)  # 调试用

    messages = build_prompt(housing_docs, query)
    try:
        answer = deepseek_chat(messages)
        return jsonify({
            "answer": answer,
            "localData": housing_list_to_markdown(housing_docs)
        })
    except Exception as e:
        return jsonify({"error": "DeepSeek API error", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5000, debug=True)