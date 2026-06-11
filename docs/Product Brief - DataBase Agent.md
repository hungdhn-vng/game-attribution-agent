**What:** Một AI agent phân tích dữ liệu game, làm rõ *câu chuyện thật* đằng sau số liệu \- chuyện gì đang xảy ra, vì sao, và khả năng tiếp theo là gì \- kèm **mức độ tin cậy rõ ràng**, và **không tự đưa ra quyết định thay con người**.  
---

## **Vấn đề \- why**

Không ai có thể dự đoán 100% các kịch bản sẽ xảy ra ⇒ Cần một AI tool giúp research & đánh giá  & nhìn ra từ dữ liệu càng nhiều kịch bản khả dĩ càng tốt, kèm bằng chứng và mức độ tin cậy.

## **Tầm nhìn**

Trở thành trợ thủ đắc lực, chỗ dựa tin cậy (nhất có thể) để đưa ra một quyết định quan trọng, giúp ta tự tin hơn trước khi hành động dựa trên dữ liệu thật sự, chứ không phải phỏng đoán.

## **Agent làm gì**

* **Tái dựng câu chuyện:** Tổng hợp dữ liệu quá khứ \+ hiện tại để trả lời "data đang thật sự kể chuyện gì, và diễn biến/rủi ro tiếp theo có khả năng là gì?"  
* **Phân tích nguyên nhân \- nội tại vs. thị trường (điểm khác biệt cốt lõi):** khi một chỉ số rớt, tự động so với game cùng genre, xu hướng toàn ngành, và cùng nhóm user ở nơi khác.  
* **Liên kết tri thức:** ghép social/trending, hiệu suất đối thủ, và nguồn vĩ mô/tài chính (vd. báo cáo World Bank, Sensor Tower, GameAnalytics, Newzoo) \- không chỉ giới hạn ở số liệu nội bộ.  
* **Nêu mức tin cậy trên 2 trục tách biệt**: *Khả năng xảy ra (likelihood)* và *Chất lượng bằng chứng (độ tin cậy phân tích)* → Một nhận định luôn đi kèm *cả hai* trục, ví dụ: "Nhiều khả năng · bằng chứng Trung bình".  
* **Tổng hợp đa module:** gộp nhiều module phân tích thành một câu chuyện thống nhất, kèm **trích dẫn nguồn** cho từng nhận định.

→ Ghép internal Data và External data để có bức tranh toàn diện → Kể ra câu chuyện đằng sau by data-driven

## **Use cases**

**1 \- Chẩn đoán (backward-looking):** phân tích hiệu suất game \- chẩn đoán biến động chỉ số (DAU, doanh thu, retention) đưa ra kịch bản kèm mức tin cậy để nhìn được các story behind nhằm hỗ trợ lường trước nước đi tiếp theo.  
**2 \- Đánh giá tiềm năng (forward-looking):** Agent **không "phán" game nào sẽ hit**; Nó phân tích để phát hiện những tín hiệu tiềm năng sớm ⇒ Quyết định đầu tư.

## **Output**

Sau khi phân tích, desire output sẽ là 1 **Attribution Hypothesis/Scenario**, gồm:

* **Nhận định chính:** câu chuyện cốt lõi trong 1–2 câu  
* **Phân tích nguyên nhân, story behind:** tách phần do bản thân game và do thị trường, kèm dẫn chứng số liệu cụ thể.  
* **Scenario tiếp theo:** 2–4 diễn biến khả dĩ, mỗi cái gắn khả năng xảy ra \+ tín hiệu cần theo dõi.  
* **Rủi ro:** các rủi ro nên lường trước, kèm mức tin cậy.  
* **Bằng chứng & nguồn:** mọi nhận định đều trích dẫn nguồn/truy vết được; nêu rõ giả định và chỗ dữ liệu còn thiếu.

  ## **Nguyên tắc bất di bất dịch**

* **Give Scenarios, Not Solutions.** Agent trình bày các kịch bản và diễn biến khả dĩ; **không** chỉ định phải làm gì. Con người quyết định.  
* **Giảm thiểu hallucinate.** Mọi nhận định phải bám vào dữ liệu truy xuất được. Nếu bằng chứng không đủ, agent **hạ mức tin cậy và nói rõ**, chứ không dựng chuyện.

  ## **USP**

1. **2 mức độ tin cậy riêng** — Mỗi nhận định nói rõ 2 điều tách bạch: *khả năng xảy ra* và *bằng chứng có chắc không*. Vì "dễ xảy ra nhưng đoán mò" rất khác "ít khi xảy ra nhưng có data chắc". Tool khác thường gộp thành 1 con số → dễ hiểu lầm.  
2. **Soi cả trong lẫn ngoài** — Game rớt chỉ số? Tool tự so với game cùng loại và xu hướng cả ngành (Sensor Tower, Newzoo) để biết: *do game mình dở, hay cả thị trường đang xuống?* Tool chỉ xem data nội bộ hoặc chỉ xem data thị trường đều không trả lời được câu này.  
3. **Cài đặt dễ, ai cũng làm được** — Thêm game/thị trường mới chỉ cần gõ vào chat, không cần code, không cần dev. PM hay BI tự setup