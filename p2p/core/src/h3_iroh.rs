// h3-quinn 소스를 iroh::endpoint 타입으로 교체한 HTTP/3 QUIC 어댑터.
// iroh가 noq(quinn 포크)를 쓰므로 API가 동일하고 교체만 하면 된다.

use std::{
    convert::TryInto,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{self, Poll},
};

use bytes::{Buf, Bytes};
use futures::{ready, stream::{self}, Stream, StreamExt};
use iroh::endpoint::{
    AcceptBi, AcceptUni, Connection as IrohConnection,
    OpenBi, OpenUni, RecvStream as IrohRecvStream, SendStream as IrohSendStream,
    VarInt,
};
use h3::{
    error::Code,
    quic::{self, ConnectionErrorIncoming, StreamErrorIncoming, StreamId, WriteBuf},
};
use tokio_util::sync::ReusableBoxFuture;

type BoxStreamSync<'a, T> = Pin<Box<dyn Stream<Item = T> + Sync + Send + 'a>>;

pub struct Connection {
    conn: IrohConnection,
    incoming_bi: BoxStreamSync<'static, <AcceptBi<'static> as Future>::Output>,
    opening_bi: Option<BoxStreamSync<'static, <OpenBi<'static> as Future>::Output>>,
    incoming_uni: BoxStreamSync<'static, <AcceptUni<'static> as Future>::Output>,
    opening_uni: Option<BoxStreamSync<'static, <OpenUni<'static> as Future>::Output>>,
}

impl Connection {
    pub fn new(conn: IrohConnection) -> Self {
        Self {
            conn: conn.clone(),
            incoming_bi: Box::pin(stream::unfold(conn.clone(), |conn| async {
                Some((conn.accept_bi().await, conn))
            })),
            opening_bi: None,
            incoming_uni: Box::pin(stream::unfold(conn.clone(), |conn| async {
                Some((conn.accept_uni().await, conn))
            })),
            opening_uni: None,
        }
    }
}

fn convert_connection_error(e: iroh::endpoint::ConnectionError) -> ConnectionErrorIncoming {
    use iroh::endpoint::ConnectionError::*;
    match e {
        ApplicationClosed(c) => ConnectionErrorIncoming::ApplicationClose {
            error_code: c.error_code.into(),
        },
        TimedOut => ConnectionErrorIncoming::Timeout,
        other => ConnectionErrorIncoming::Undefined(Arc::new(other)),
    }
}

impl<B: Buf> quic::Connection<B> for Connection {
    type RecvStream = RecvStream;
    type OpenStreams = OpenStreams;

    fn poll_accept_bidi(
        &mut self,
        cx: &mut task::Context<'_>,
    ) -> Poll<Result<Self::BidiStream, ConnectionErrorIncoming>> {
        let (send, recv) = ready!(self.incoming_bi.poll_next_unpin(cx))
            .expect("incoming_bi never returns None")
            .map_err(convert_connection_error)?;
        Poll::Ready(Ok(BidiStream {
            send: SendStream::new(send),
            recv: RecvStream::new(recv),
        }))
    }

    fn poll_accept_recv(
        &mut self,
        cx: &mut task::Context<'_>,
    ) -> Poll<Result<Self::RecvStream, ConnectionErrorIncoming>> {
        let recv = ready!(self.incoming_uni.poll_next_unpin(cx))
            .expect("incoming_uni never returns None")
            .map_err(convert_connection_error)?;
        Poll::Ready(Ok(RecvStream::new(recv)))
    }

    fn opener(&self) -> Self::OpenStreams {
        OpenStreams { conn: self.conn.clone(), opening_bi: None, opening_uni: None }
    }
}

impl<B: Buf> quic::OpenStreams<B> for Connection {
    type SendStream = SendStream<B>;
    type BidiStream = BidiStream<B>;

    fn poll_open_bidi(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<Self::BidiStream, StreamErrorIncoming>> {
        let bi = self.opening_bi.get_or_insert_with(|| {
            Box::pin(stream::unfold(self.conn.clone(), |conn| async {
                Some((conn.open_bi().await, conn))
            }))
        });
        let (send, recv) = ready!(bi.poll_next_unpin(cx))
            .expect("BoxStream does not return None")
            .map_err(|e| StreamErrorIncoming::ConnectionErrorIncoming {
                connection_error: convert_connection_error(e),
            })?;
        Poll::Ready(Ok(BidiStream { send: SendStream::new(send), recv: RecvStream::new(recv) }))
    }

    fn poll_open_send(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<Self::SendStream, StreamErrorIncoming>> {
        let uni = self.opening_uni.get_or_insert_with(|| {
            Box::pin(stream::unfold(self.conn.clone(), |conn| async {
                Some((conn.open_uni().await, conn))
            }))
        });
        let send = ready!(uni.poll_next_unpin(cx))
            .expect("BoxStream does not return None")
            .map_err(|e| StreamErrorIncoming::ConnectionErrorIncoming {
                connection_error: convert_connection_error(e),
            })?;
        Poll::Ready(Ok(SendStream::new(send)))
    }

    fn close(&mut self, code: Code, reason: &[u8]) {
        self.conn.close(VarInt::from_u64(code.value()).expect("error code VarInt"), reason);
    }
}

pub struct OpenStreams {
    conn: IrohConnection,
    opening_bi: Option<BoxStreamSync<'static, <OpenBi<'static> as Future>::Output>>,
    opening_uni: Option<BoxStreamSync<'static, <OpenUni<'static> as Future>::Output>>,
}

impl<B: Buf> quic::OpenStreams<B> for OpenStreams {
    type SendStream = SendStream<B>;
    type BidiStream = BidiStream<B>;

    fn poll_open_bidi(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<Self::BidiStream, StreamErrorIncoming>> {
        let bi = self.opening_bi.get_or_insert_with(|| {
            Box::pin(stream::unfold(self.conn.clone(), |conn| async {
                Some((conn.open_bi().await, conn))
            }))
        });
        let (send, recv) = ready!(bi.poll_next_unpin(cx))
            .expect("BoxStream does not return None")
            .map_err(|e| StreamErrorIncoming::ConnectionErrorIncoming {
                connection_error: convert_connection_error(e),
            })?;
        Poll::Ready(Ok(BidiStream { send: SendStream::new(send), recv: RecvStream::new(recv) }))
    }

    fn poll_open_send(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<Self::SendStream, StreamErrorIncoming>> {
        let uni = self.opening_uni.get_or_insert_with(|| {
            Box::pin(stream::unfold(self.conn.clone(), |conn| async {
                Some((conn.open_uni().await, conn))
            }))
        });
        let send = ready!(uni.poll_next_unpin(cx))
            .expect("BoxStream does not return None")
            .map_err(|e| StreamErrorIncoming::ConnectionErrorIncoming {
                connection_error: convert_connection_error(e),
            })?;
        Poll::Ready(Ok(SendStream::new(send)))
    }

    fn close(&mut self, code: Code, reason: &[u8]) {
        self.conn.close(VarInt::from_u64(code.value()).expect("error code VarInt"), reason);
    }
}

pub struct BidiStream<B: Buf> {
    send: SendStream<B>,
    recv: RecvStream,
}

impl<B: Buf> quic::BidiStream<B> for BidiStream<B> {
    type SendStream = SendStream<B>;
    type RecvStream = RecvStream;
    fn split(self) -> (Self::SendStream, Self::RecvStream) { (self.send, self.recv) }
}

impl<B: Buf> quic::RecvStream for BidiStream<B> {
    type Buf = Bytes;
    fn poll_data(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<Option<Self::Buf>, StreamErrorIncoming>> {
        self.recv.poll_data(cx)
    }
    fn stop_sending(&mut self, error_code: u64) { self.recv.stop_sending(error_code) }
    fn recv_id(&self) -> StreamId { self.recv.recv_id() }
}

impl<B: Buf> quic::SendStream<B> for BidiStream<B> {
    fn poll_ready(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<(), StreamErrorIncoming>> { self.send.poll_ready(cx) }
    fn poll_finish(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<(), StreamErrorIncoming>> { self.send.poll_finish(cx) }
    fn reset(&mut self, reset_code: u64) { self.send.reset(reset_code) }
    fn send_data<D: Into<WriteBuf<B>>>(&mut self, data: D) -> Result<(), StreamErrorIncoming> { self.send.send_data(data) }
    fn send_id(&self) -> StreamId { self.send.send_id() }
}

impl<B: Buf> quic::SendStreamUnframed<B> for BidiStream<B> {
    fn poll_send<D: Buf>(&mut self, cx: &mut task::Context<'_>, buf: &mut D) -> Poll<Result<usize, StreamErrorIncoming>> {
        self.send.poll_send(cx, buf)
    }
}

type ReadChunkFuture = ReusableBoxFuture<
    'static,
    (IrohRecvStream, Result<Option<iroh::endpoint::Chunk>, iroh::endpoint::ReadError>),
>;

pub struct RecvStream {
    stream: Option<IrohRecvStream>,
    read_chunk_fut: ReadChunkFuture,
}

impl RecvStream {
    fn new(stream: IrohRecvStream) -> Self {
        Self {
            stream: Some(stream),
            read_chunk_fut: ReusableBoxFuture::new(async { unreachable!() }),
        }
    }
}

impl quic::RecvStream for RecvStream {
    type Buf = Bytes;

    fn poll_data(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<Option<Self::Buf>, StreamErrorIncoming>> {
        if let Some(mut stream) = self.stream.take() {
            self.read_chunk_fut.set(async move {
                let chunk = stream.read_chunk(usize::MAX).await;
                (stream, chunk)
            });
        }
        let (stream, chunk) = ready!(self.read_chunk_fut.poll(cx));
        self.stream = Some(stream);
        Poll::Ready(Ok(chunk.map_err(convert_read_error)?.map(|c| c.bytes)))
    }

    fn stop_sending(&mut self, error_code: u64) {
        self.stream.as_mut().unwrap()
            .stop(VarInt::from_u64(error_code).expect("invalid error_code"))
            .ok();
    }

    fn recv_id(&self) -> StreamId {
        let num: u64 = self.stream.as_ref().unwrap().id().into();
        num.try_into().expect("invalid stream id")
    }
}

fn convert_read_error(e: iroh::endpoint::ReadError) -> StreamErrorIncoming {
    use iroh::endpoint::ReadError::*;
    match e {
        Reset(v) => StreamErrorIncoming::StreamTerminated { error_code: v.into_inner() },
        ConnectionLost(e) => StreamErrorIncoming::ConnectionErrorIncoming {
            connection_error: convert_connection_error(e),
        },
        other => StreamErrorIncoming::Unknown(Box::new(other)),
    }
}

fn convert_write_error(e: iroh::endpoint::WriteError) -> StreamErrorIncoming {
    use iroh::endpoint::WriteError::*;
    match e {
        Stopped(v) => StreamErrorIncoming::StreamTerminated { error_code: v.into_inner() },
        ConnectionLost(e) => StreamErrorIncoming::ConnectionErrorIncoming {
            connection_error: convert_connection_error(e),
        },
        other => StreamErrorIncoming::Unknown(Box::new(other)),
    }
}

pub struct SendStream<B: Buf> {
    stream: IrohSendStream,
    writing: Option<WriteBuf<B>>,
}

impl<B: Buf> SendStream<B> {
    fn new(stream: IrohSendStream) -> Self {
        Self { stream, writing: None }
    }
}

impl<B: Buf> quic::SendStream<B> for SendStream<B> {
    fn poll_ready(&mut self, cx: &mut task::Context<'_>) -> Poll<Result<(), StreamErrorIncoming>> {
        if let Some(ref mut data) = self.writing {
            while data.has_remaining() {
                let written = ready!(Pin::new(&mut self.stream).poll_write(cx, data.chunk()))
                    .map_err(convert_write_error)?;
                data.advance(written);
            }
        }
        self.writing = None;
        Poll::Ready(Ok(()))
    }

    fn poll_finish(&mut self, _cx: &mut task::Context<'_>) -> Poll<Result<(), StreamErrorIncoming>> {
        Poll::Ready(self.stream.finish().map_err(|e| StreamErrorIncoming::Unknown(Box::new(e))))
    }

    fn reset(&mut self, reset_code: u64) {
        let _ = self.stream.reset(VarInt::from_u64(reset_code).unwrap_or(VarInt::MAX));
    }

    fn send_data<D: Into<WriteBuf<B>>>(&mut self, data: D) -> Result<(), StreamErrorIncoming> {
        if self.writing.is_some() {
            return Err(StreamErrorIncoming::ConnectionErrorIncoming {
                connection_error: ConnectionErrorIncoming::InternalError(
                    "send_data called while not ready".to_string(),
                ),
            });
        }
        self.writing = Some(data.into());
        Ok(())
    }

    fn send_id(&self) -> StreamId {
        let num: u64 = self.stream.id().into();
        num.try_into().expect("invalid stream id")
    }
}

impl<B: Buf> quic::SendStreamUnframed<B> for SendStream<B> {
    fn poll_send<D: Buf>(&mut self, cx: &mut task::Context<'_>, buf: &mut D) -> Poll<Result<usize, StreamErrorIncoming>> {
        if self.writing.is_some() { panic!("poll_send called while not ready") }
        match ready!(Pin::new(&mut self.stream).poll_write(cx, buf.chunk())) {
            Ok(n) => { buf.advance(n); Poll::Ready(Ok(n)) }
            Err(e) => Poll::Ready(Err(convert_write_error(e))),
        }
    }
}
