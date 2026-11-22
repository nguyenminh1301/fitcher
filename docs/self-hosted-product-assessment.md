# fitcher: từ bộ sáu dịch vụ thành một container tự host

Ngày 2026-11-12. Tài liệu này ghi lại đánh giá, các quyết định và lộ trình đưa fitcher thành sản phẩm mã nguồn mở mà một lập trình viên tự host bằng một lệnh Docker.
Quyết định ràng buộc nằm ở [DECISIONS.md](DECISIONS.md) (bản v4); thứ tự thực hiện ở [MASTER_PLAN.md](MASTER_PLAN.md), mỗi phase một file trong [plans/](plans/README.md).

## Kết luận ngắn

- Đích đến là **một image, một container, một volume, một cổng**. Người dùng chạy một lệnh, mở trình duyệt và đi qua trình thiết lập bốn bước: chế độ dùng, mô hình, nguồn dữ liệu, tài liệu.
- Ba trong sáu dịch vụ biến mất: Keycloak, LiteLLM Proxy và Qdrant. ClickHouse được giữ lại theo quyết định của chủ dự án và chạy như một tiến trình bên trong container.
- Trở ngại lớn nhất với người mới không phải là đóng gói mà là bước chuẩn bị dữ liệu: hiện phải viết mart bằng dbt và duyệt Domain Pack trước khi hỏi được câu đầu tiên. Lộ trình có một phase riêng để bỏ rào cản này.
- Thứ tự thực hiện khác thứ tự ưu tiên bạn nêu ở một điểm: image một container chỉ làm được **sau khi** Keycloak và LiteLLM Proxy đã rời khỏi stack, nên hai việc đó đi trước.

## Hiện trạng đo được

Đo trên stack đang chạy ở máy phát triển (hai pack mẫu, chưa có tải):

| Dịch vụ | RAM | Image | Sau thay đổi |
|---|---|---|---|
| api (có mô hình sàng lọc ONNX) | 1,47 GB | 1,1 GB | Giữ; mô hình sàng lọc thành tuỳ chọn |
| ClickHouse | 744 MB | 1,2 GB | Giữ, chạy trong cùng container với cấu hình ít bộ nhớ |
| Keycloak | 434 MB | 751 MB | Bỏ |
| Qdrant | 221 MB | 277 MB | Chạy nội bộ ở phase 16, bỏ hẳn ở phase 20 |
| LiteLLM Proxy | 206 MB | 1,81 GB | Bỏ; dùng thư viện LiteLLM ngay trong api |
| web | 71 MB | 417 MB | Giữ, chạy trong cùng container |

Tổng hiện tại khoảng 3,1 GB RAM, 5,5 GB image, README yêu cầu Docker có 8 GB. Volume mô hình sàng lọc chiếm thêm 1,1 GB đĩa.
Mức sau thay đổi là ước lượng, chưa đo: bỏ Keycloak, LiteLLM Proxy và Qdrant giải phóng khoảng 860 MB RAM và 2,8 GB image; phase 16 phải đo lại và ghi số thật.

## Trả lời câu hỏi về ClickHouse

**Vì sao cần ClickHouse khi dữ liệu đã ở PostgreSQL?** PostgreSQL trong repo chỉ là fixture đóng vai hệ thống nguồn của khách. ClickHouse đang làm bốn việc: là động cơ truy vấn duy nhất của agent (một phương ngữ SQL), là lớp phân quyền thật (role, quyền theo cột, row policy), lưu log và hội thoại, và lưu sổ đăng ký tài liệu.

**Nguồn SQL Server có phải đi qua ClickHouse không?** Có, và đây là điểm yếu nhất của thiết kế. ClickHouse có engine riêng cho PostgreSQL và MySQL nhưng không có cho SQL Server; đường duy nhất là cầu ODBC với driver FreeTDS, chạy qua một tiến trình `clickhouse-odbc-bridge` riêng ([hướng dẫn của ClickHouse](https://clickhouse.com/docs/knowledgebase/how-to-set-up-ch-on-docker-odbc-connect-mssql), [hàm `odbc`](https://clickhouse.com/docs/sql-reference/table-functions/odbc)). Vì vậy SQL Server có phase riêng, bắt đầu bằng một thử nghiệm có tiêu chí đạt.

**Kiến trúc này có cần thiết không?** Không bắt buộc về mặt kỹ thuật: agent có thể sinh SQL theo từng phương ngữ và truy vấn thẳng nguồn. Nhưng giữ ClickHouse là hợp lý với quyết định của bạn, vì ba lý do có bằng chứng:

- Một phương ngữ SQL nghĩa là một bộ prompt, một bộ kiểm tra sqlglot và một bộ eval. Hỗ trợ ba phương ngữ nhân ba phần việc dễ sai nhất của sản phẩm.
- Phân quyền theo vai trò đang dựa hoàn toàn vào ClickHouse; bỏ nó thì chế độ nhóm phải viết lại lớp bảo mật.
- chDB, bản ClickHouse nhúng trong tiến trình, không ghi nhận hỗ trợ người dùng, vai trò hay row policy trong tài liệu ([chDB](https://clickhouse.com/docs/chdb)), nên không thay được server ở chế độ nhóm.

Cái giá phải nói thẳng: ClickHouse là thành phần nặng nhất còn lại (file nhị phân 763 MB, 744 MB RAM khi rảnh).

## Những chỗ tôi không đồng ý với yêu cầu ban đầu

1. **"Truy vấn trực tiếp là mặc định" không đi cùng "dữ liệu trên 50 GB".** Với engine PostgreSQL, ClickHouse chỉ đẩy xuống nguồn các điều kiện `WHERE` đơn giản; join, tổng hợp và sắp xếp chạy trong ClickHouse sau khi kéo dữ liệu về ([tài liệu engine PostgreSQL](https://clickhouse.com/docs/engines/table-engines/integrations/postgresql)). Một câu "doanh thu theo tháng" trên bảng 50 GB sẽ kéo gần hết bảng qua mạng ở mỗi lần hỏi. Quyết định: trực tiếp là mặc định cho bảng nhỏ, còn bảng lớn thì trình thiết lập đề xuất sao chép dựa trên kích thước đọc từ nguồn. Người dùng vẫn đổi được.
2. **"Laptop 8 GB" và "trên 50 GB" chạy được nhưng không nhanh.** ClickHouse khuyến nghị 32 GB RAM, cảnh báo dưới 16 GB sẽ gặp lỗi bộ nhớ với cấu hình mặc định, và chạy được từ 2 GB nếu chỉnh cấu hình ([khuyến nghị vận hành](https://clickhouse.com/docs/operations/tips)). Image sẽ mang sẵn cấu hình ít bộ nhớ, nhưng tài liệu cài đặt phải nói rõ giới hạn này.
3. **"Không có tài liệu thì bỏ Qdrant" dựa trên hiểu sai.** Qdrant chứa sáu bộ chỉ mục, năm trong đó là glossary, metric, dataset, giá trị cột và ví dụ. Không có chúng agent không tìm được metric. Cách bỏ Qdrant đúng là chuyển tìm kiếm vào ClickHouse cho mọi cài đặt; lựa chọn "không dùng tài liệu" chỉ tắt phần tải lên và chỉ mục tài liệu.
4. **Gộp web và api thành một tiến trình là không đáng.** Web đang dùng route handler phía server của Next.js để giữ phiên và chuyển tiếp tới api, nên không xuất thành file tĩnh được nếu không viết lại. Giải pháp là một image chứa cả hai tiến trình. `docker ps` vẫn chỉ hiện một container.
5. **Chế độ không đăng nhập không thể tự biết mình có bị mở ra mạng hay không.** Docker công bố cổng ra mọi địa chỉ theo mặc định ([tài liệu công bố cổng](https://docs.docker.com/engine/network/port-publishing/)). Lệnh cài đặt sẽ gắn cổng vào `127.0.0.1`, và ứng dụng từ chối mọi yêu cầu có `Host` khác localhost khi ở chế độ cá nhân.

## Quyết định cho từng yêu cầu

| Yêu cầu | Quyết định |
|---|---|
| Cách cài đặt | Chỉ Docker. Một lệnh `docker run`; thêm một file Compose mẫu cho người muốn ClickHouse bên ngoài. Không làm bản native. |
| Một image, một container | Một image chứa ba tiến trình (web, api, ClickHouse) do s6-overlay giám sát. Mẫu này giống Enfyra: mặc định dùng dịch vụ nhúng, đặt biến môi trường để trỏ ra dịch vụ ngoài ([Enfyra Docker](https://enfyra.io/docs/docker)). Docker cho phép nhiều tiến trình trong một container nhưng yêu cầu tiến trình chính quản lý tiến trình con đúng cách ([tài liệu Docker](https://docs.docker.com/engine/containers/multi-service_container/)). |
| Khoá API và mô hình cục bộ | Trình thiết lập có bước Mô hình: chọn nhà cung cấp, dán khoá hoặc nhập URL (Ollama, LM Studio, endpoint tương thích OpenAI), bấm Kiểm tra, tự gán mô hình cho từng tầng. Khoá được mã hoá trong volume và không bao giờ trả về trình duyệt. |
| Cổng LLM | Thư viện LiteLLM chạy trong tiến trình api thay cho LiteLLM Proxy. Tài liệu LiteLLM mô tả Proxy dành cho nhóm nền tảng quản lý truy cập toàn tổ chức, còn SDK dành cho ứng dụng gọi trực tiếp, vẫn có Router, retry và ghi chi phí ([LiteLLM](https://docs.litellm.ai/docs/)). |
| Embedding | Mặc định dùng mô hình cục bộ đa ngôn ngữ `paraphrase-multilingual-MiniLM-L12-v2` (384 chiều, 0,22 GB) qua fastembed ([danh sách mô hình](https://qdrant.github.io/fastembed/examples/Supported_Models/)). Người chỉ có khoá Anthropic hay chỉ dùng Ollama vẫn chạy được. Phải qua eval truy hồi tiếng Việt trước khi chốt. |
| Kết nối database | Trang Nguồn dữ liệu và một bước trong trình thiết lập: PostgreSQL, MySQL/MariaDB, SQL Server, file CSV/Excel/Parquet. Thông tin đăng nhập được tạo thành named collection bằng SQL và lưu mã hoá trong ClickHouse ([named collections](https://clickhouse.com/docs/operations/named-collections)), nên api và LLM không bao giờ giữ mật khẩu nguồn. |
| Cá nhân hay nhóm | Chọn trong trình thiết lập, đổi được về sau. Cá nhân: không đăng nhập, chỉ localhost. Nhóm: tài khoản có sẵn trong ứng dụng (Argon2id, phiên lưu phía server), OIDC là tuỳ chọn. Keycloak bị bỏ ở cả hai chế độ. |
| Tài liệu cho LLM | Bật theo mặc định; tắt thì ẩn trang Tài liệu và không tạo chỉ mục `kb_docs`. |
| Dùng được ngay | Sau khi nối nguồn, ứng dụng tự tạo dataset từ bảng đã chọn, tự nhận quan hệ từ khoá ngoại và soạn pack nháp dùng được ngay; duyệt và eval thành việc tuỳ chọn, có nhãn "chưa duyệt". |
| Dữ liệu demo | Image phát hành không chứa pack hay dataset mẫu. Bản demo công khai là web chạy chế độ dữ liệu mẫu sẵn có, không có backend. Pack mẫu ở lại repo cho việc phát triển và eval. |
| Trạng thái ứng dụng | Cài đặt, khoá đã mã hoá, tài khoản và phiên lưu trong một file SQLite ở volume. ClickHouse không phù hợp cho dữ liệu cần ràng buộc duy nhất và giao dịch. |

## Điểm yếu về hiệu năng và bảo mật

Đã kiểm chứng trong repo hoặc bằng số đo:

| Điểm yếu | Hậu quả | Xử lý ở phase |
|---|---|---|
| Phiên đăng nhập của web nằm trong bộ nhớ tiến trình | Khởi động lại là mất phiên của mọi người | 15 |
| Không có cơ chế nâng cấp schema; script khởi tạo chỉ chạy trên volume mới | Người dùng nâng image lên bản mới sẽ hỏng dữ liệu cũ | 13 |
| Hội thoại hết hạn sau 90 ngày cùng với log | Người dùng mất lịch sử làm việc | 21 |
| ClickHouse chạy cấu hình mặc định, không giới hạn bộ nhớ server | Lỗi bộ nhớ trên máy 8 GB | 16 |
| api chạy một worker, giới hạn tần suất đếm theo từng tiến trình | Không tăng worker được mà không sai bộ đếm | 21 |
| Mô hình sàng lọc luôn nạp, thiếu thì chặn mọi câu hỏi | 1,1 GB đĩa và phần lớn RAM của api cho một tính năng người dùng cá nhân ít cần | 14 |
| Mật khẩu và khoá nằm ở dạng thô trong `.env` | Lộ file là lộ hết | 13, 14, 17 |
| Sao chép nguồn là nạp lại toàn bộ, không có lịch chạy | Bảng lớn không cập nhật thường xuyên được | 17 |

Rủi ro mới do hướng đi này tạo ra:

- **Chuỗi cung ứng.** Hai bản LiteLLM 1.82.7 và 1.82.8 trên PyPI đã bị cài mã đánh cắp thông tin đăng nhập vào ngày 24/3/2026, bắt nguồn từ công cụ quét Trivy bị xâm nhập trong CI ([BleepingComputer](https://bleepingcomputer.com/news/security/popular-litellm-pypi-package-compromised-in-teampcp-supply-chain-attack), [Help Net Security](https://www.helpnetsecurity.com/2026/03/25/teampcp-supply-chain-attacks/)). Repo này dùng cả LiteLLM lẫn Trivy. Biện pháp: khoá phụ thuộc theo hash, ghim image nền và GitHub Action theo digest, không tự động nâng phiên bản.
- **Chế độ không đăng nhập.** Một trang web độc hại có thể gọi tới `localhost` của người dùng. Biện pháp: kiểm tra `Host` và `Origin`, cookie `SameSite=Strict` cho mọi yêu cầu thay đổi trạng thái.
- **Form kết nối database.** Người nhập host tuỳ ý có thể dùng ứng dụng để dò mạng nội bộ. Biện pháp: chỉ quản trị viên được tạo nguồn ở chế độ nhóm, tài khoản nguồn chỉ đọc, và thông báo lỗi kết nối không lộ chi tiết mạng.
- **Một container nhiều tiến trình.** Một tiến trình chết phải kéo container dừng hoặc được khởi động lại có kiểm soát; healthcheck phải phản ánh cả ba.
- **Chìa khoá mã hoá nằm cùng volume với dữ liệu.** Nó bảo vệ được bản sao lưu và file bị lộ, không bảo vệ được máy đã bị chiếm. Người cần mức cao hơn đặt chìa qua biến môi trường.

## Lộ trình

Mỗi phase là một nhánh và một hoặc vài PR vào `develop`. Agent thực hiện chỉ cần đọc DECISIONS.md và file phase tương ứng.

| Phase | Nội dung | Kết quả người dùng thấy |
|---|---|---|
| [13](plans/phase-13-app-state-and-setup.md) | Kho trạng thái SQLite, mã hoá bí mật, nâng cấp schema, khung trình thiết lập | Màn hình thiết lập lần đầu |
| [14](plans/phase-14-model-providers.md) | LiteLLM trong tiến trình, bước Mô hình, embedding cục bộ, sàng lọc tuỳ chọn | Nhập khoá hoặc nối Ollama trên giao diện; bớt một container |
| [15](plans/phase-15-sign-in-modes.md) | Chế độ cá nhân và nhóm, tài khoản có sẵn, OIDC tuỳ chọn | Không còn Keycloak |
| [16](plans/phase-16-single-container-image.md) | Một image, một lệnh, cấu hình ít bộ nhớ, phát hành lên registry | `docker run` một lệnh, `docker ps` một dòng |
| [17](plans/phase-17-data-source-connections.md) | Trang Nguồn dữ liệu cho PostgreSQL, MySQL và file; lịch sao chép | Nối database trên giao diện |
| [18](plans/phase-18-sql-server-sources.md) | SQL Server qua ODBC | Nối SQL Server |
| [19](plans/phase-19-instant-pack.md) | Pack tự sinh từ nguồn đã nối | Hỏi được ngay sau khi nối database |
| [20](plans/phase-20-search-in-clickhouse.md) | Tìm kiếm trong ClickHouse, tài liệu thành tuỳ chọn | Còn ba tiến trình, không còn Qdrant |
| [21](plans/phase-21-hardening-and-release.md) | Bảo mật, hiệu năng, sao lưu, bản demo, bản phát hành đầu | Bản 1.0 |

Phase 16 mang Qdrant vào trong container như một tiến trình nội bộ để có sớm "một lệnh"; phase 20 mới thay nó. Nếu tìm kiếm trong ClickHouse không đạt mức truy hồi hiện tại, Qdrant nội bộ ở lại và phase 20 dừng ở đó.

## Việc còn mở

- SQL Server qua ODBC chưa được thử trong repo này; phase 18 có thể kết luận là không khả thi trong image chung.
- Mô hình embedding cục bộ chưa được đo trên bộ câu hỏi tiếng Việt của dự án.
- Chất lượng trả lời khi bỏ mart viết tay (phase 19) là rủi ro lớn nhất về sản phẩm; hai pack mẫu và eval hiện có là thước đo.
- Kết nối qua đường hầm SSH, MongoDB và S3 trên giao diện, và đồng bộ thay đổi liên tục (CDC) nằm ngoài lộ trình này.

## Nguồn

Các trang đã đọc trong đợt nghiên cứu ngày 2026-11-12:

- Enfyra, hướng dẫn Docker: <https://enfyra.io/docs/docker>
- Docker, chạy nhiều tiến trình trong một container: <https://docs.docker.com/engine/containers/multi-service_container/>
- Docker, công bố cổng: <https://docs.docker.com/engine/network/port-publishing/>
- ClickHouse, engine PostgreSQL: <https://clickhouse.com/docs/engines/table-engines/integrations/postgresql>
- ClickHouse, khuyến nghị vận hành: <https://clickhouse.com/docs/operations/tips>
- ClickHouse, named collections: <https://clickhouse.com/docs/operations/named-collections>
- ClickHouse, nối SQL Server qua ODBC: <https://clickhouse.com/docs/knowledgebase/how-to-set-up-ch-on-docker-odbc-connect-mssql>
- ClickHouse, chDB: <https://clickhouse.com/docs/chdb>
- LiteLLM, SDK và Proxy: <https://docs.litellm.ai/docs/>
- fastembed, mô hình được hỗ trợ: <https://qdrant.github.io/fastembed/examples/Supported_Models/>
- Open WebUI, lệnh cài một dòng và `host.docker.internal`: <https://docs.openwebui.com/>
- BleepingComputer và Help Net Security về vụ LiteLLM trên PyPI (liên kết ở trên)

Tham khảo thêm, không tải lại trong đợt này: [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) cho Argon2id, và [SQLite: Appropriate Uses](https://www.sqlite.org/whentouse.html) cho kho trạng thái.
