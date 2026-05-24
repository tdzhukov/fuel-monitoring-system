# Build stage
FROM golang:1.21.13-alpine AS builder
RUN apk add --no-cache git
WORKDIR /app
COPY go.mod ./
RUN go mod download
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o bridge .

# Run stage
FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /app
COPY --from=builder /app/bridge .
EXPOSE 8090
CMD ["./bridge"]
