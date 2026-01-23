using System;
using System.Net;
using System.Net.Sockets;
using CADverse.Utils;

namespace CADverse.Communication
{
    /// <summary>
    /// QR 코드 파싱 및 검증을 담당하는 헬퍼 클래스
    /// </summary>
    public static class QrCommunication
    {
        /// <summary>
        /// QR 페이로드를 파싱하여 호스트와 포트를 추출한다.
        /// </summary>
        public static Result<AddressInfo> ParseQrPayload(string qrPayload)
        {
            if (string.IsNullOrWhiteSpace(qrPayload))
            {
                return Result<AddressInfo>.Failure("QR 데이터가 비어 있습니다.");
            }

            string trimmed = qrPayload.Trim();

            // 주소 파싱
            var parseResult = TryParseAddress(trimmed);
            if (!parseResult.IsSuccess)
            {
                return Result<AddressInfo>.Failure($"유효하지 않은 주소 형식: {qrPayload}");
            }

            var addressInfo = parseResult.Value;

            // 보안 검증: 로컬 네트워크만 허용
            if (!IsLocalNetworkAddress(addressInfo.Host))
            {
                return Result<AddressInfo>.Failure("허용되는 로컬 IP 주소가 아닙니다.");
            }

            // 경로 검증: /cadverse 경로 확인
            if (!IsCadversePath(addressInfo.Path))
            {
                return Result<AddressInfo>.Failure("QR 경로에 /cadverse 가 필요합니다.");
            }

            return Result<AddressInfo>.Success(addressInfo);
        }

        private static Result<AddressInfo> TryParseAddress(string address)
        {
            // 경로 분리
            int pathIndex = address.IndexOf('/');
            string addressPart = pathIndex >= 0 ? address.Substring(0, pathIndex) : address;
            string path = pathIndex >= 0 ? address.Substring(pathIndex) : "/";

            // 포트 분리
            int portIndex = addressPart.LastIndexOf(':');
            if (portIndex < 0)
            {
                return Result<AddressInfo>.Failure("포트 정보가 없습니다.");
            }

            string host = addressPart.Substring(0, portIndex);
            if (!int.TryParse(addressPart.Substring(portIndex + 1), out int port))
            {
                return Result<AddressInfo>.Failure("포트 번호가 유효하지 않습니다.");
            }

            if (string.IsNullOrEmpty(host))
            {
                return Result<AddressInfo>.Failure("호스트 주소가 비어 있습니다.");
            }

            if (port <= 0 || port > 65535)
            {
                return Result<AddressInfo>.Failure("포트 번호는 1-65535 범위여야 합니다.");
            }

            return Result<AddressInfo>.Success(new AddressInfo(host, port, path));
        }

        private static bool IsCadversePath(string path)
        {
            var normalizedPath = path?.TrimEnd('/');
            return string.Equals(normalizedPath, "/cadverse", StringComparison.OrdinalIgnoreCase);
        }

        private static bool IsLocalNetworkAddress(string host)
        {
            if (string.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (!IPAddress.TryParse(host, out var address))
            {
                return false;
            }

            if (address.AddressFamily != AddressFamily.InterNetwork)
            {
                return false;
            }

            var octets = address.GetAddressBytes();
            return
                octets[0] == 10 ||
                (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) ||
                (octets[0] == 192 && octets[1] == 168) ||
                octets[0] == 127;
        }
    }

    /// <summary>
    /// 파싱된 주소 정보
    /// </summary>
    public readonly struct AddressInfo
    {
        public readonly string Host;
        public readonly int Port;
        public readonly string Path;

        public AddressInfo(string host, int port, string path)
        {
            Host = host;
            Port = port;
            Path = path;
        }
    }
}
