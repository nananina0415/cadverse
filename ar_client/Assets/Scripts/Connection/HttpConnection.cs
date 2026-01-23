using System;
using System.Net.Http;
using System.Threading.Tasks;

namespace CADverse.Connection
{
    /// <summary>
    /// 순수 HTTP 통신을 담당하는 저수준 클래스.
    /// 어떤 리소스를 가져오는지는 알 필요 없이, 단순히 HTTP GET 요청만 처리한다.
    /// </summary>
    public sealed class HttpConnection : IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly string _baseUrl;

        /// <summary>
        /// HTTP 연결을 생성한다.
        /// </summary>
        /// <param name="baseUrl">기본 URL (예: "http://192.168.0.1:8000")</param>
        public HttpConnection(string baseUrl)
        {
            if (string.IsNullOrWhiteSpace(baseUrl))
            {
                throw new ArgumentException("Base URL은 비어있을 수 없습니다.", nameof(baseUrl));
            }

            _baseUrl = baseUrl.TrimEnd('/');
            _httpClient = new HttpClient
            {
                BaseAddress = new Uri(_baseUrl),
                Timeout = TimeSpan.FromSeconds(30)
            };
        }

        /// <summary>
        /// 기본 URL을 반환한다.
        /// </summary>
        public string BaseUrl => _baseUrl;

        /// <summary>
        /// 지정된 경로에서 텍스트 데이터를 가져온다.
        /// </summary>
        /// <param name="path">요청 경로 (예: "/models/box.sdf")</param>
        /// <returns>응답 텍스트</returns>
        public async Task<string> GetTextAsync(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                throw new ArgumentException("경로는 비어있을 수 없습니다.", nameof(path));
            }

            var response = await _httpClient.GetAsync(path);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadAsStringAsync();
        }

        /// <summary>
        /// 지정된 경로에서 바이너리 데이터를 가져온다.
        /// </summary>
        /// <param name="path">요청 경로</param>
        /// <returns>응답 바이트 배열</returns>
        public async Task<byte[]> GetBytesAsync(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                throw new ArgumentException("경로는 비어있을 수 없습니다.", nameof(path));
            }

            var response = await _httpClient.GetAsync(path);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadAsByteArrayAsync();
        }

        public void Dispose()
        {
            _httpClient?.Dispose();
        }
    }
}
