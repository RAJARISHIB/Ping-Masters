// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title LiquidationArchive
 * @notice Permanent, low-cost liquidation ledger deployed on opBNB Testnet.
 *
 *         After every successful BSC liquidation, the FastAPI bot sends a
 *         logLiquidation() transaction here.  opBNB fees are near-zero, so
 *         every event is permanently and cheaply archived.
 *
 *         Each record now includes the debt currency (USD=0 / INR=1) so the
 *         dashboard can display amounts with the correct symbol and format.
 */
contract LiquidationArchive {

    // ─── TYPES ───────────────────────────────────────────────────────────────

    /// @notice Mirrors PriceConsumer.Currency without importing the contract.
    uint8 public constant CURRENCY_USD = 0;
    uint8 public constant CURRENCY_INR = 1;

    struct LiquidationRecord {
        address borrower;
        address liquidator;
        uint256 debtRepaid;        // 18-decimal in user's chosen currency
        uint256 collateralSeized;  // Total BNB seized including bonus (wei)
        uint256 bonusSeized;       // Bonus BNB portion (wei)
        uint8   currency;          // 0 = USD, 1 = INR
        uint256 timestamp;
        uint256 bscBlockNumber;
        bytes32 bscTxHash;         // Cross-chain reference to BSC tx
    }

    // ─── STATE ───────────────────────────────────────────────────────────────

    LiquidationRecord[] public liquidations;

    uint256 public totalDebtRepaidUSD;       // cumulative pmUSD repaid (18-dec)
    uint256 public totalDebtRepaidINR;       // cumulative pmINR repaid (18-dec)
    uint256 public totalCollateralSeized;    // cumulative BNB seized (wei)
    uint256 public totalLiquidationEvents;

    mapping(address => uint256) public liquidationCount;

    address public owner;
    address public loggerBot;  // FastAPI bot wallet authorised to log events

    // ─── EVENTS ──────────────────────────────────────────────────────────────

    event LiquidationLogged(
        uint256 indexed recordId,
        address indexed borrower,
        address indexed liquidator,
        uint256 debtRepaid,
        uint256 collateralSeized,
        uint8   currency,
        bytes32 bscTxHash
    );
    event LoggerBotUpdated(address indexed bot);
    event OwnershipTransferred(address indexed previous, address indexed next_);

    // ─── ERRORS ──────────────────────────────────────────────────────────────

    error Unauthorized();
    error ZeroAddress();
    error InvalidRecord();
    error RecordNotFound();
    error InvalidCurrency();

    // ─── CONSTRUCTOR ─────────────────────────────────────────────────────────

    constructor() {
        owner = msg.sender;
    }

    // ─── MODIFIERS ───────────────────────────────────────────────────────────

    modifier onlyAuthorised() {
        if (msg.sender != owner && msg.sender != loggerBot) revert Unauthorized();
        _;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    // ─── WRITE ───────────────────────────────────────────────────────────────

    /**
     * @notice Record a completed BSC liquidation.
     *         Called by the FastAPI bot after the BSC tx is confirmed.
     *
     * @param borrower          Address liquidated on BSC.
     * @param liquidator        Address that called liquidate() on BSC.
     * @param debtRepaid        pmUSD or pmINR repaid (18-decimal).
     * @param collateralSeized  Total BNB seized including bonus (wei).
     * @param bonusSeized       Bonus BNB portion (wei).
     * @param currency          0 = USD, 1 = INR.
     * @param bscBlockNumber    BSC block number of the liquidation tx.
     * @param bscTxHash         BSC transaction hash (cross-chain proof).
     * @return recordId         Index of the new record in the array.
     */
    function logLiquidation(
        address borrower,
        address liquidator,
        uint256 debtRepaid,
        uint256 collateralSeized,
        uint256 bonusSeized,
        uint8   currency,
        uint256 bscBlockNumber,
        bytes32 bscTxHash
    ) external onlyAuthorised returns (uint256 recordId) {
        if (borrower   == address(0)) revert InvalidRecord();
        if (liquidator == address(0)) revert InvalidRecord();
        if (debtRepaid == 0)          revert InvalidRecord();
        if (currency > 1)             revert InvalidCurrency();

        recordId = liquidations.length;

        liquidations.push(LiquidationRecord({
            borrower:         borrower,
            liquidator:       liquidator,
            debtRepaid:       debtRepaid,
            collateralSeized: collateralSeized,
            bonusSeized:      bonusSeized,
            currency:         currency,
            timestamp:        block.timestamp,
            bscBlockNumber:   bscBlockNumber,
            bscTxHash:        bscTxHash
        }));

        totalCollateralSeized += collateralSeized;
        totalLiquidationEvents++;
        liquidationCount[borrower]++;

        if (currency == CURRENCY_USD) {
            totalDebtRepaidUSD += debtRepaid;
        } else {
            totalDebtRepaidINR += debtRepaid;
        }

        emit LiquidationLogged(
            recordId, borrower, liquidator,
            debtRepaid, collateralSeized, currency, bscTxHash
        );
    }

    // ─── READ ─────────────────────────────────────────────────────────────────

    /**
     * @notice Protocol-wide stats — feeds the dashboard UI.
     * @return totalEvents      Total liquidations ever logged.
     * @return totalUSD         Cumulative pmUSD repaid (18-dec).
     * @return totalINR         Cumulative pmINR repaid (18-dec).
     * @return totalBNBSeized   Cumulative BNB seized (wei).
     */
    function getGlobalStats()
        external
        view
        returns (
            uint256 totalEvents,
            uint256 totalUSD,
            uint256 totalINR,
            uint256 totalBNBSeized
        )
    {
        totalEvents    = totalLiquidationEvents;
        totalUSD       = totalDebtRepaidUSD;
        totalINR       = totalDebtRepaidINR;
        totalBNBSeized = totalCollateralSeized;
    }

    /// @notice Get a single record by ID.
    function getLiquidation(uint256 recordId)
        external
        view
        returns (LiquidationRecord memory)
    {
        if (recordId >= liquidations.length) revert RecordNotFound();
        return liquidations[recordId];
    }

    function getTotalRecords() external view returns (uint256) {
        return liquidations.length;
    }

    /**
     * @notice Paginated history for the UI (lazy-load the table).
     */
    function getLiquidationsPaginated(uint256 offset, uint256 pageSize)
        external
        view
        returns (LiquidationRecord[] memory page)
    {
        uint256 total = liquidations.length;
        if (offset >= total) return new LiquidationRecord[](0);
        uint256 end = offset + pageSize;
        if (end > total) end = total;
        page = new LiquidationRecord[](end - offset);
        for (uint256 i = offset; i < end; i++) {
            page[i - offset] = liquidations[i];
        }
    }

    /// @notice All record IDs where `borrower` was the target.
    function getLiquidationsByBorrower(address borrower)
        external
        view
        returns (uint256[] memory ids)
    {
        uint256 count = liquidationCount[borrower];
        ids = new uint256[](count);
        uint256 idx;
        for (uint256 i = 0; i < liquidations.length && idx < count; i++) {
            if (liquidations[i].borrower == borrower) ids[idx++] = i;
        }
    }

    // ─── ADMIN ───────────────────────────────────────────────────────────────

    /// @notice Authorise the FastAPI bot wallet to log liquidations.
    function setLoggerBot(address bot) external onlyOwner {
        if (bot == address(0)) revert ZeroAddress();
        loggerBot = bot;
        emit LoggerBotUpdated(bot);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }
}
