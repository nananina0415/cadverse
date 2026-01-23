using System;

/// <summary>
/// 성공 또는 실패를 나타내는 결과 타입. 에러 메시지와 함께 값을 반환할 수 있다.
/// </summary>
public readonly struct Result<T>
{
    private readonly T _value;
    private readonly string _error;

    public bool IsSuccess { get; }
    public T Value => IsSuccess ? _value : throw new InvalidOperationException("Result가 실패 상태입니다. Value에 접근할 수 없습니다.");
    public string Error => IsSuccess ? throw new InvalidOperationException("Result가 성공 상태입니다. Error에 접근할 수 없습니다.") : _error;

    private Result(bool isSuccess, T value, string error)
    {
        IsSuccess = isSuccess;
        _value = value;
        _error = error ?? string.Empty;
    }

    public static Result<T> Success(T value) => new Result<T>(true, value, null);
    public static Result<T> Failure(string error) => new Result<T>(false, default(T), error);

    public static implicit operator bool(Result<T> result) => result.IsSuccess;
    public static implicit operator Result<T>(T value) => Success(value);

    public Result<TOther> Map<TOther>(Func<T, TOther> mapper)
    {
        return IsSuccess ? Result<TOther>.Success(mapper(_value)) : Result<TOther>.Failure(_error);
    }

    public Result<TOther> Bind<TOther>(Func<T, Result<TOther>> binder)
    {
        return IsSuccess ? binder(_value) : Result<TOther>.Failure(_error);
    }
}

/// <summary>
/// 값이 없는 결과 타입 (성공/실패만)
/// </summary>
public readonly struct Result
{
    private readonly string _error;

    public bool IsSuccess { get; }
    public string Error => IsSuccess ? throw new InvalidOperationException("Result가 성공 상태입니다. Error에 접근할 수 없습니다.") : _error;

    private Result(bool isSuccess, string error)
    {
        IsSuccess = isSuccess;
        _error = error ?? string.Empty;
    }

    public static Result Success() => new Result(true, null);
    public static Result Failure(string error) => new Result(false, error);

    public static implicit operator bool(Result result) => result.IsSuccess;
}

