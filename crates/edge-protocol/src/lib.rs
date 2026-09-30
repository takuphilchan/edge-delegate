//! Strict framing, preview-service messages and Linux same-user transport checks.
pub mod action_adapter;
pub mod adapter;
pub mod execution;
pub mod execution_v2;
#[cfg(target_os = "linux")]
pub mod local;
pub mod service;
use edge_contracts::{MAX_FRAME_BYTES, parse_json};
use serde::{Serialize, de::DeserializeOwned};
use std::io::{self, Read, Write};

fn invalid(error: impl ToString) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, error.to_string())
}

/// Four-byte big-endian byte length followed by one strict UTF-8 JSON document.
/// Returns None only for clean EOF before a header, never for a partial frame.
pub fn read_frame<T: DeserializeOwned>(reader: &mut impl Read) -> io::Result<Option<T>> {
    let mut header = [0_u8; 4];
    loop {
        match reader.read(&mut header[..1]) {
            Ok(0) => return Ok(None),
            Ok(_) => break,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    reader.read_exact(&mut header[1..])?;
    let length = u32::from_be_bytes(header) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err(invalid("frame length must be 1..65536 bytes"));
    }
    let mut bytes = vec![0; length];
    reader.read_exact(&mut bytes)?;
    parse_json(&bytes).map(Some).map_err(invalid)
}

pub fn write_frame<T: Serialize>(writer: &mut impl Write, value: &T) -> io::Result<()> {
    // A bounded writer prevents allocating an unbounded serialized frame.
    struct Bounded(Vec<u8>);
    impl Write for Bounded {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if bytes.len() > MAX_FRAME_BYTES - self.0.len() {
                return Err(invalid("frame exceeds 65536 bytes"));
            }
            self.0.extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    let mut payload = Bounded(Vec::new());
    serde_json::to_writer(&mut payload, value).map_err(invalid)?;
    // Reject invalid UTF-8/duplicate keys even for custom Serialize implementations.
    let _: serde_json::Value = parse_json(&payload.0).map_err(invalid)?;
    writer.write_all(&(payload.0.len() as u32).to_be_bytes())?;
    writer.write_all(&payload.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};
    use std::io::Cursor;

    #[test]
    fn multiple_frames_round_trip_without_consuming_the_next() {
        let mut bytes = Vec::new();
        write_frame(&mut bytes, &json!({"text": "héllo"})).unwrap();
        write_frame(&mut bytes, &json!({"second": true})).unwrap();
        let mut reader = Cursor::new(bytes);
        assert_eq!(
            read_frame::<Value>(&mut reader).unwrap(),
            Some(json!({"text": "héllo"}))
        );
        assert_eq!(
            read_frame::<Value>(&mut reader).unwrap(),
            Some(json!({"second": true}))
        );
        assert!(read_frame::<Value>(&mut reader).unwrap().is_none());
    }

    #[test]
    fn short_header_short_body_and_invalid_lengths_fail() {
        for bytes in [
            vec![0],
            vec![0, 0, 0, 2, b'{'],
            vec![0, 0, 0, 0],
            vec![0xff; 4],
        ] {
            assert!(read_frame::<Value>(&mut Cursor::new(bytes)).is_err());
        }
    }

    #[test]
    fn duplicate_json_is_not_admitted_by_framing() {
        let body = br#"{"a":1,"a":2}"#;
        let mut bytes = (body.len() as u32).to_be_bytes().to_vec();
        bytes.extend_from_slice(body);
        assert!(read_frame::<Value>(&mut Cursor::new(bytes)).is_err());
    }

    #[test]
    fn oversized_serialization_writes_nothing() {
        let mut bytes = Vec::new();
        assert!(write_frame(&mut bytes, &"a".repeat(MAX_FRAME_BYTES)).is_err());
        assert!(bytes.is_empty());
    }
}
