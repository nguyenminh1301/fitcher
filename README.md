# Finch

Finch là dự án hỏi đáp dữ liệu bằng ngôn ngữ tự nhiên. Người dùng nhập câu hỏi, hệ thống sinh SQL, truy vấn dữ liệu và trả kết quả dưới dạng bảng, biểu đồ và phần tóm tắt.

## Trạng thái

Khởi tạo repository. Hiện chỉ có tài liệu giới thiệu và `.gitignore`; chưa có code ứng dụng hoặc lệnh chạy.

## Kiến trúc dự kiến

- **Frontend:** Next.js, Plotly — giao diện chat, bảng kết quả, biểu đồ và xem SQL.
- **Backend:** FastAPI — API và SSE để cập nhật kết quả theo từng bước.
- **Agent:** LangGraph — lấy ngữ cảnh, sinh SQL, kiểm tra, thực thi và sửa lỗi SQL.
- **Truy vấn:** DuckDB trên dữ liệu Parquet NYC TLC HVFHV.
- **Lưu trữ:** PostgreSQL + pgvector cho dictionary, glossary và lịch sử hội thoại.
- **Triển khai:** Docker Compose với ba service `web`, `api`, `db`.

## Model OpenAI

| Tác vụ | Model dự kiến |
| --- | --- |
| Sinh và sửa SQL | `gpt-6.1-sol` |
| Tóm tắt và chọn biểu đồ | `gpt-6-luna` |
| Embedding dictionary, glossary và câu hỏi | `text-embedding-3-small` |

Backend dự kiến dùng OpenAI Python SDK, Responses API và Embeddings API. Embedding lưu trong pgvector với 1536 chiều; dữ liệu và câu hỏi phải dùng cùng model và số chiều.

`OPENAI_API_KEY` sẽ được cấu hình ở backend và script ingest qua biến môi trường. Không commit API key hoặc file `.env`.

## Luồng xử lý dự kiến

1. Người dùng nhập câu hỏi trên giao diện chat.
2. Agent lấy schema và glossary liên quan qua tìm kiếm vector.
3. Model sinh SQL; sqlglot kiểm tra SELECT-only, bảng được phép và giới hạn số dòng.
4. DuckDB thực thi truy vấn với giới hạn thời gian và bộ nhớ.
5. Nếu có lỗi, agent sửa SQL trong giới hạn số lần thử lại.
6. Backend trả SQL, dữ liệu, biểu đồ và tóm tắt về giao diện qua SSE.

## Bước tiếp theo

- Khởi tạo frontend Next.js và backend FastAPI.
- Thiết lập Docker Compose, PostgreSQL và pgvector.
- Chuẩn bị Parquet và ingest dictionary/glossary.
- Xây dựng luồng hỏi đáp đầu tiên từ câu hỏi đến kết quả.
